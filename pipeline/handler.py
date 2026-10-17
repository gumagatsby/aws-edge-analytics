"""Pipeline steps that Step Functions calls between the Glue job and the dashboard.

Actions (the event's "action" field):
  resolve    which day(s) to process: {"day"}, {"days"}, {"start","end"} or nothing (yesterday, UTC)
  ensure     create tables if missing and rebuild the small dimensions (sql/ensure.sql)
  sql        run sql/<name>.sql for one day
  reconcile  check every layer holds the same rows for a day; fail if not (N3)
  publish    write the dashboard's data file and refresh it at the edge
"""
import datetime as dt
import json
import os
import pathlib
import re
import string
import time

import boto3

# In the Lambda package the SQL sits next to this file; in the repository it is ../sql.
_here = pathlib.Path(__file__).resolve().parent
SQL_DIR = _here / "sql" if (_here / "sql").is_dir() else _here.parent / "sql"
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
athena = boto3.client("athena")


class ReconciliationError(Exception):
    """Row counts differ between layers."""


def valid_day(value: str) -> str:
    # Days are interpolated into SQL, so only a real calendar date gets through.
    if not isinstance(value, str) or not DAY.match(value):
        raise ValueError(f"Not a date: {value!r}")
    return dt.date.fromisoformat(value).isoformat()


def render(name: str, day: str | None = None) -> list[str]:
    text = (SQL_DIR / f"{name}.sql").read_text()
    values = {"clean": os.environ["CLEAN_DB"], "curated": os.environ["CURATED_DB"],
              "lake": os.environ["LAKE_BUCKET"], "artifacts": os.environ["ARTIFACTS_BUCKET"]}
    if day is not None:
        values["day"] = valid_day(day)
    # Comments go first so placeholder examples in them are never substituted.
    text = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
    text = string.Template(text).substitute(values)
    return [s.strip() for s in text.split(";") if s.strip()]


def query(sql: str) -> list[dict]:
    qid = athena.start_query_execution(QueryString=sql, WorkGroup=os.environ["WORKGROUP"])["QueryExecutionId"]
    delay = 0.5
    while True:
        state = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if state["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(delay)
        delay = min(delay * 1.5, 5)
    if state["State"] != "SUCCEEDED":
        raise RuntimeError(f"{state['State']}: {state.get('StateChangeReason', '')}\n{sql[:300]}")
    rows, header, token = [], None, None
    while True:
        page = athena.get_query_results(QueryExecutionId=qid, **({"NextToken": token} if token else {}))
        for r in page["ResultSet"]["Rows"]:
            values = [c.get("VarCharValue") for c in r["Data"]]
            if header is None:
                header = values
                continue
            rows.append(dict(zip(header, values)))
        token = page.get("NextToken")
        if not token:
            return rows


def resolve(event):
    if "days" in event:
        days = [valid_day(d) for d in event["days"]]
    elif "day" in event:
        days = [valid_day(event["day"])]
    elif "start" in event:
        start, end = dt.date.fromisoformat(valid_day(event["start"])), dt.date.fromisoformat(valid_day(event["end"]))
        days = [(start + dt.timedelta(n)).isoformat() for n in range((end - start).days + 1)]
    else:
        days = [(dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat()]
    if not days or len(days) > 31:
        raise ValueError("Process between 1 and 31 days per run")
    return {"days": days}


def run_sql(name, day=None):
    statements = render(name, day)
    for s in statements:
        query(s)
    return {"name": name, "day": day, "statements": len(statements)}


def reconcile(day):
    day = valid_day(day)
    clean, curated = os.environ["CLEAN_DB"], os.environ["CURATED_DB"]
    audit = {r["source"]: r for r in query(
        f"SELECT source, raw_lines, clean_rows, quarantined_rows, balanced FROM {clean}.run_audit WHERE day = DATE '{day}'")}
    clean_rows = {r["source"]: int(r["n"]) for r in query(
        f"SELECT source, count(*) AS n FROM {clean}.requests WHERE day = DATE '{day}' GROUP BY 1")}
    fact_rows = {r["source"]: int(r["n"]) for r in query(
        f"SELECT source, count(*) AS n FROM {curated}.fact_request WHERE day = DATE '{day}' GROUP BY 1")}
    agg_rows = {r["source"]: int(r["n"]) for r in query(
        f"SELECT source, sum(requests) AS n FROM {curated}.agg_edge_daily WHERE day = DATE '{day}' GROUP BY 1")}
    report, problems = {}, []
    for source, a in audit.items():
        raw, cl, q = int(a["raw_lines"]), int(a["clean_rows"]), int(a["quarantined_rows"])
        layers = {"raw": raw, "quarantined": q, "clean (audit)": cl, "clean (table)": clean_rows.get(source, 0),
                  "fact": fact_rows.get(source, 0), "report": agg_rows.get(source, 0)}
        report[source] = layers
        if raw != cl + q:
            problems.append(f"{source}: raw {raw} != clean {cl} + quarantined {q}")
        if len({cl, layers["clean (table)"], layers["fact"], layers["report"]}) != 1:
            problems.append(f"{source}: clean, fact and report rows differ: {layers}")
    if not audit:
        problems.append("no audit rows for this day")
    if problems:
        raise ReconciliationError("; ".join(problems))
    return {"day": day, "layers": report}


def publish(event):
    from publish import build  # kept separate: it is long and only needed here
    data = build(query, os.environ["CURATED_DB"], os.environ["CLEAN_DB"])
    body = json.dumps(data, separators=(",", ":"), default=str).encode()
    boto3.client("s3").put_object(Bucket=os.environ["SITE_BUCKET"], Key="insights/data.json", Body=body,
                                  ContentType="application/json", CacheControl="max-age=300")
    boto3.client("cloudfront").create_invalidation(
        DistributionId=os.environ["DISTRIBUTION_ID"],
        InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["/insights/data.json"]},
                           "CallerReference": str(time.time_ns())})
    return {"bytes": len(body), "days": len(data.get("days", []))}


def handler(event, context):
    action = event.get("action")
    if action == "resolve":
        # Step Functions passes the execution input under "input".
        return resolve(event.get("input", event))
    if action == "ensure":
        return run_sql("ensure")
    if action == "sql":
        if event.get("name") not in ("fact", "aggregates"):
            raise ValueError("Unknown SQL file")
        return run_sql(event["name"], event["day"])
    if action == "reconcile":
        return reconcile(event["day"])
    if action == "publish":
        return publish(event)
    raise ValueError(f"Unknown action {action!r}")
