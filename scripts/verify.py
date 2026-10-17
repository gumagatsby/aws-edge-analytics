"""Check the non-functional requirements against the deployed platform.

Each check prints PASS or FAIL with its measurement, and the output is the evidence
kept in docs/evidence. Run with credentials for the deploying account.

    python scripts/verify.py n1            # no raw IP address beyond the raw layer
    python scripts/verify.py n2            # analyst vs data engineer access
    python scripts/verify.py n3            # every run reconciles
    python scripts/verify.py n4-snapshot 2026-10-12 before.json
    python scripts/verify.py n4-compare before.json after.json
    python scripts/verify.py n7            # origin reachable only through CloudFront
"""
import argparse
import gzip
import hashlib
import ipaddress
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

import boto3

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "glue"))
from edge_etl.fields import FIELDS  # noqa: E402

REGION = "eu-west-2"
CIP = FIELDS.index("c-ip")
# Columns that change on every run by design, left out of the re-run comparison.
VOLATILE = {"run_id", "finished_at"}
# Candidate addresses: dotted quads not preceded by "/" or a letter (which would make
# them a version number such as Chrome/131.0.0.0), and IPv6 with "::" or eight groups.
IPV4 = re.compile(r"(?<![0-9A-Za-z/.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])")
IPV6 = re.compile(r"(?i)(?<![0-9a-f:])(?:(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}|(?:[0-9a-f]{1,4}:)*[0-9a-f]{0,4}::(?:[0-9a-f]{1,4}:?)*)(?![0-9a-f:])")
ATHENA_IPV4 = r"(^|[^0-9A-Za-z/.])([0-9]{1,3}\.){3}[0-9]{1,3}($|[^0-9.])"
ATHENA_IPV6 = r"(?i)(([0-9a-f]{1,4}:){7}[0-9a-f]{1,4}|[0-9a-f:]*::[0-9a-f:]*)"

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}", flush=True)


def outputs():
    raw = subprocess.run(["terraform", "output", "-json"], cwd=ROOT / "terraform", capture_output=True, text=True, check=True)
    return {k: v["value"] for k, v in json.loads(raw.stdout).items()}


def session_for(role_arn=None):
    if not role_arn:
        return boto3.Session(region_name=REGION)
    creds = boto3.client("sts").assume_role(RoleArn=role_arn, RoleSessionName="verify")["Credentials"]
    return boto3.Session(aws_access_key_id=creds["AccessKeyId"], aws_secret_access_key=creds["SecretAccessKey"],
                         aws_session_token=creds["SessionToken"], region_name=REGION)


def athena(sql, workgroup, session=None, header=False):
    """Run a query. Returns (rows, error); rows exclude the header unless asked for."""
    client = (session or session_for()).client("athena")
    try:
        qid = client.start_query_execution(QueryString=sql, WorkGroup=workgroup)["QueryExecutionId"]
    except client.exceptions.ClientError as e:
        return None, str(e)
    while True:
        status = client.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if status["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(1)
    if status["State"] != "SUCCEEDED":
        return None, status.get("StateChangeReason", status["State"])
    rows, token = [], None
    while True:
        kw = {"QueryExecutionId": qid, **({"NextToken": token} if token else {})}
        page = client.get_query_results(**kw)
        rows += [[c.get("VarCharValue") for c in r["Data"]] for r in page["ResultSet"]["Rows"]]
        token = page.get("NextToken")
        if not token:
            return (rows if header else rows[1:]), None


def tables(db):
    glue = boto3.client("glue", region_name=REGION)
    for page in glue.get_paginator("get_tables").paginate(DatabaseName=db):
        yield from page["TableList"]


def raw_ips(bucket):
    """Every client address in the raw layer. Held in memory only, never written."""
    s3 = boto3.client("s3", region_name=REGION)
    found = set()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith(".gz"):
                continue
            body = gzip.decompress(s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()).decode()
            for line in body.splitlines():
                if line and not line.startswith("#"):
                    parts = line.split("\t")
                    if len(parts) > CIP and parts[CIP] != "-":
                        found.add(parts[CIP])
    return found


def normalise(addr):
    try:
        return str(ipaddress.ip_address(addr))
    except ValueError:
        return None


def is_network(value):
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    prefix = 24 if addr.version == 4 else 48
    return ipaddress.ip_network(f"{addr}/{prefix}", strict=False).network_address == addr


def n1(out):
    ips = {normalise(a) for a in raw_ips(out["raw_bucket"])} - {None}
    print(f"raw layer holds {len(ips)} distinct client addresses (kept in memory only)")
    # The clean layer is read as the deploying identity; the curated layer as the data
    # engineer, who is granted every column there.
    layers = [(out["clean_db"], out["workgroup"], None),
              (out["curated_db"], out["people_workgroups"]["data-engineer"], session_for(out["engineer_role_arn"]))]
    leaks, scanned = [], 0
    for db, workgroup, session in layers:
        for t in tables(db):
            cols = [c["Name"] for c in t["StorageDescriptor"]["Columns"] if c["Type"] == "string"]
            for col in cols:
                scanned += 1
                sql = (f'SELECT DISTINCT "{col}" FROM "{db}"."{t["Name"]}" WHERE regexp_like("{col}", \'{ATHENA_IPV4}\') '
                       f'OR regexp_like("{col}", \'{ATHENA_IPV6}\')')
                rows, err = athena(sql, workgroup, session)
                if err:
                    check(f"N1 scan {db}.{t['Name']}.{col}", False, err[:200])
                    continue
                if col == "client_network":
                    # Holds network addresses by design. A raw address that ends in .0 equals its
                    # own /24, so the test is that every value is a /24 or /48 network address.
                    loose = [v for (v,) in rows if v and not is_network(v)]
                    check(f"N1 {db}.{t['Name']}.client_network holds only /24 and /48 networks", not loose,
                          f"{len(rows)} distinct values, {len(loose)} not network addresses")
                    continue
                for (value,) in rows:
                    for cand in IPV4.findall(value or "") + IPV6.findall(value or ""):
                        if normalise(cand) in ips:
                            leaks.append(f"{db}.{t['Name']}.{col}")
    check("N1 no raw client address in any string column of the clean or curated layer", not leaks,
          f"{scanned} columns scanned; leaks in: {sorted(set(leaks)) or 'none'}")
    rules = boto3.client("s3", region_name=REGION).get_bucket_lifecycle_configuration(Bucket=out["raw_bucket"])["Rules"]
    days = [r["Expiration"]["Days"] for r in rules if r.get("Status") == "Enabled" and "Expiration" in r]
    check("N1 raw logs expire after 7 days", days == [7], f"expiration rules: {days}")


def n2(out):
    curated, clean = out["curated_db"], out["clean_db"]
    analyst = session_for(out["analyst_role_arn"])
    engineer = session_for(out["engineer_role_arn"])
    wg = out["people_workgroups"]

    def allowed(session, workgroup, sql):
        rows, err = athena(sql, workgroup, session)
        return err is None, (err or "")[:160]

    ok, err = allowed(analyst, wg["analyst"], f"SELECT count(*) FROM {curated}.agg_edge_daily")
    check("N2 analyst can query report tables", ok, err)
    ok, err = allowed(analyst, wg["analyst"], f"SELECT count(*), count(DISTINCT path) FROM {curated}.fact_request")
    check("N2 analyst can query the request table without visitor_id", ok, err)
    ok, err = allowed(analyst, wg["analyst"], f"SELECT visitor_id FROM {curated}.fact_request LIMIT 1")
    check("N2 analyst cannot read visitor_id", not ok, err)
    rows, err = athena(f"SELECT * FROM {curated}.fact_request LIMIT 1", wg["analyst"], analyst, header=True)
    check("N2 analyst SELECT * returns every column except visitor_id",
          err is None and "visitor_id" not in rows[0] and "path" in rows[0], err or f"{len(rows[0])} columns returned")
    ok, err = allowed(analyst, wg["analyst"], f"SELECT count(*) FROM {clean}.requests")
    check("N2 analyst cannot query the clean layer", not ok, err)
    ok, err = allowed(analyst, wg["data-engineer"], "SELECT 1")
    check("N2 analyst cannot use the data engineer's workgroup", not ok, err)
    ok, err = allowed(engineer, wg["data-engineer"], f"SELECT visitor_id FROM {curated}.fact_request LIMIT 1")
    check("N2 data engineer can read visitor_id", ok, err)
    # The result file of the engineer's query is not readable by the analyst.
    s3 = analyst.client("s3")
    location = boto3.client("athena", region_name=REGION).get_work_group(
        WorkGroup=wg["data-engineer"])["WorkGroup"]["Configuration"]["ResultConfiguration"]["OutputLocation"]
    b, prefix = location[len("s3://"):].split("/", 1)
    keys = boto3.client("s3", region_name=REGION).list_objects_v2(Bucket=b, Prefix=prefix, MaxKeys=1).get("Contents", [])
    if keys:
        try:
            s3.get_object(Bucket=b, Key=keys[0]["Key"])
            check("N2 analyst cannot open the engineer's query results", False, keys[0]["Key"])
        except s3.exceptions.ClientError as e:
            check("N2 analyst cannot open the engineer's query results", True, e.response["Error"]["Code"])


def n3(out):
    rows, err = athena(f"SELECT CAST(day AS varchar), source, raw_lines, clean_rows, quarantined_rows, balanced "
                       f"FROM {out['clean_db']}.run_audit ORDER BY day, source", out["workgroup"])
    if err:
        return check("N3 run audit readable", False, err)
    for day, source, raw, clean, quarantined, balanced in rows:
        print(f"  {day} {source:9} raw {int(raw):>8,} = clean {int(clean):>8,} + quarantined {int(quarantined):>5,}  {balanced}")
    check("N3 every run reconciles (raw = clean + quarantined)", all(r[5] == "true" for r in rows), f"{len(rows)} day/source runs")


def snapshot(out, day):
    """Row count and order-independent checksum of every row for one day, per table."""
    snap = {}
    layers = [(out["clean_db"], out["workgroup"], None),
              (out["curated_db"], out["people_workgroups"]["data-engineer"], session_for(out["engineer_role_arn"]))]
    for db, workgroup, session in layers:
        for t in tables(db):
            cols = {c["Name"]: c["Type"] for c in t["StorageDescriptor"]["Columns"] + t.get("PartitionKeys", [])}
            if "day" not in cols or t["Name"] == "run_audit":
                continue

            def text(name, kind):
                value = f"array_join(\"{name}\", ',')" if kind.startswith("array") else f"CAST(\"{name}\" AS varchar)"
                return f"coalesce({value}, '~')"
            row = ", ".join(text(c, k) for c, k in cols.items() if c not in VOLATILE)
            sql = (f"SELECT count(*), to_hex(checksum(concat_ws('|', ARRAY[{row}]))) "
                   f"FROM \"{db}\".\"{t['Name']}\" WHERE day = DATE '{day}'")
            rows, err = athena(sql, workgroup, session)
            snap[f"{db}.{t['Name']}"] = err[:160] if err else {"rows": int(rows[0][0]), "checksum": rows[0][1]}
    return snap


def n4_compare(a, b):
    before, after = json.loads(pathlib.Path(a).read_text()), json.loads(pathlib.Path(b).read_text())
    for table in sorted(before):
        same = before[table] == after.get(table)
        print(f"  {table:45} {before[table]}  {'same' if same else 'DIFFERENT ' + str(after.get(table))}")
    check("N4 re-processing a day gives identical tables (rows and checksums)",
          before == after and all(isinstance(v, dict) for v in before.values()), f"{len(before)} tables compared")


def n7(out):
    def status(url):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "verify"}), timeout=15).status
        except urllib.error.HTTPError as e:
            return e.code
    site = out["site_url"]
    check("N7 site through CloudFront", status(f"{site}/") == 200)
    check("N7 API through CloudFront", status(f"{site}/api/health") == 200)
    s = status(f"https://{out['site_bucket']}.s3.{REGION}.amazonaws.com/index.html")
    check("N7 site bucket directly is refused", s == 403, f"HTTP {s}")
    s = status(f"{out['api_function_url'].rstrip('/')}/api/health")
    check("N7 API function URL directly is refused", s == 403, f"HTTP {s}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("check", choices=["n1", "n2", "n3", "n4-snapshot", "n4-compare", "n7"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    if a.check == "n4-compare":
        n4_compare(*a.args)
    else:
        out = outputs()
        if a.check == "n4-snapshot":
            day, path = a.args
            pathlib.Path(path).write_text(json.dumps(snapshot(out, day), indent=2))
            print(f"snapshot of {day} written to {path}")
        else:
            {"n1": n1, "n2": n2, "n3": n3, "n7": n7}[a.check](out)
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
