import re
from urllib.parse import quote

import pytest

from edge_etl.transform import FIELDS, parse

KEY = b"test-key"
BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15"
T0 = 1792187956433  # 2026-10-16T21:59:16.433Z


def line(**over):
    v = {
        "date": "2026-10-16", "time": "21:59:16", "timestamp(ms)": str(T0), "x-edge-location": "TLV55-P3",
        "sc-bytes": "384", "c-ip": "198.51.100.23", "cs-method": "GET", "cs(Host)": "d1.cloudfront.net",
        "cs-uri-stem": "/products/3.html", "sc-status": "200", "cs(Referer)": "-", "cs(User-Agent)": quote(BROWSER),
        "cs-uri-query": "-", "cs(Cookie)": "-", "x-edge-result-type": "Hit", "x-edge-request-id": "req-1",
        "x-host-header": "d1.cloudfront.net", "cs-protocol": "https", "cs-bytes": "60", "time-taken": "0.012",
        "x-forwarded-for": "-", "ssl-protocol": "TLSv1.3", "ssl-cipher": "TLS_AES_128_GCM_SHA256",
        "x-edge-response-result-type": "Hit", "cs-protocol-version": "HTTP/2.0", "time-to-first-byte": "0.011",
        "x-edge-detailed-result-type": "Hit", "sc-content-type": "text/html", "sc-content-len": "900",
        "c-country": "GB", "asn": "14593", "cache-behavior-path-pattern": "*",
        "viewer-request-log-data": quote("ab=B;new=1"),
    }
    v.update(over)
    return "\t".join(v[f] for f in FIELDS)


def run(spark, lines):
    df = spark.createDataFrame([(l, "s3://raw/f.gz", "real") for l in lines], "value string, log_file string, source string")
    clean, quarantine = parse(df, KEY)
    return [r.asDict() for r in clean.collect()], [r.asDict() for r in quarantine.collect()]


def test_parses_a_browser_request_without_keeping_the_ip(spark):
    clean, quarantine = run(spark, ["#Version: 1.0", "#Fields: x", line()])
    assert quarantine == [] and len(clean) == 1
    r = clean[0]
    assert r["client_network"] == "198.51.100.0"
    assert re.fullmatch(r"[0-9a-f]{32}", r["visitor_id"])
    assert r["edge_code"] == "TLV" and r["country"] == "GB" and r["status"] == 200
    assert r["ab_group"] == "B" and r["ab_new_visitor"] is True
    assert r["user_agent"] == BROWSER and r["content_group"] == "product"
    assert str(r["event_ts"]).startswith("2026-10-16 21:59:16")
    assert not any("198.51.100.23" in str(v) for v in r.values())


def test_ipv6_is_truncated_to_a_48(spark):
    clean, _ = run(spark, [line(**{"c-ip": "2001:db8:abcd:12:34:56:78:9"})])
    assert clean[0]["client_network"] == "2001:db8:abcd::"


def test_same_visitor_same_id_different_key_different_id(spark):
    from pyspark.sql import functions as F
    df = spark.createDataFrame([(line(), "f", "real")], "value string, log_file string, source string")
    a = parse(df, b"k1")[0].select("visitor_id").first()[0]
    b = parse(df, b"k1")[0].select("visitor_id").first()[0]
    c = parse(df, b"k2")[0].select("visitor_id").first()[0]
    assert a == b != c


def test_bad_lines_are_quarantined_with_a_reason_and_masked_ip(spark):
    bad = [
        line(**{"timestamp(ms)": "yesterday"}),
        line(**{"sc-status": "OK"}),
        line(**{"x-edge-request-id": "-"}),
        line(**{"x-edge-location": "??"}),
        "198.51.100.23\ttruncated line",
        line(**{"c-ip": "2001:db8:85a3::8a2e:370:7334", "sc-status": "OK", "x-edge-request-id": "v6"}),
        "2001:0db8:85a3:0000:0000:8a2e:0370:7334\ttruncated v6 line",
    ]
    clean, quarantine = run(spark, bad + [line(**{"x-edge-request-id": "ok"})])
    assert len(clean) == 1 and len(quarantine) == 7
    assert sorted(q["reason"] for q in quarantine) == sorted([
        "unparseable timestamp", "unparseable status", "unparseable status", "missing request id",
        "malformed edge location", "expected 33 fields, got 2", "expected 33 fields, got 2"])
    for q in quarantine:
        assert "198.51.100.23" not in q["line"]
        assert "8a2e" not in q["line"].lower(), q["line"]
        assert "21:59:16" in q["line"] or "truncated" in q["line"]  # times are not mistaken for IPv6


def test_own_ip_in_kept_text_is_flagged_but_version_numbers_are_not(spark):
    chrome = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
    clean, _ = run(spark, [
        line(**{"cs(User-Agent)": quote(chrome), "x-edge-request-id": "r1"}),
        line(**{"cs-uri-stem": "/track/198.51.100.23", "x-edge-request-id": "r2"}),
        line(**{"cs(Referer)": quote("https://example.com/?from=198.51.100.23"), "x-edge-request-id": "r3"}),
    ])
    flags = {r["request_id"]: r["ip_in_text"] for r in clean}
    assert flags == {"r1": False, "r2": True, "r3": True}


def test_tracking_parameters_counted_and_only_names_kept(spark):
    clean, _ = run(spark, [line(**{"cs-uri-query": "utm_source=mail&colour=red&gclid=abc&email=a@b.com"})])
    r = clean[0]
    assert r["query_keys"] == ["colour", "email", "gclid", "utm_source"]
    assert r["tracking_params"] == 2
    assert "a@b.com" not in str(r)


@pytest.mark.parametrize("ua,expected,reason", [
    ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", "known_bot", "known crawler user agent"),
    ("curl/8.7.1", "suspected_bot", "scripted or missing user agent"),
    ("-", "suspected_bot", "scripted or missing user agent"),
    (BROWSER, "human", None),
])
def test_user_agent_rules(spark, ua, expected, reason):
    clean, _ = run(spark, [line(**{"cs(User-Agent)": quote(ua) if ua != "-" else "-"}),
                           line(**{"cs-uri-stem": "/css/site.css", "x-edge-request-id": "r2",
                                   "cs(User-Agent)": quote(ua) if ua != "-" else "-"})])
    page = next(r for r in clean if r["content_group"] == "product")
    assert (page["bot_class"], page["bot_reason"]) == (expected, reason)


def test_request_rate_rule(spark):
    burst = [line(**{"x-edge-request-id": f"b{i}", "timestamp(ms)": str(T0 + i * 100),
                     "c-ip": f"203.0.113.{i % 200}", "cs-uri-stem": "/css/site.css"}) for i in range(121)]
    clean, _ = run(spark, burst)
    assert {r["bot_reason"] for r in clean} == {"request rate"}


def test_pages_without_assets_rule(spark):
    pages = [line(**{"x-edge-request-id": f"p{i}", "cs-uri-stem": f"/products/{i}.html",
                     "timestamp(ms)": str(T0 + i * 5000)}) for i in range(5)]
    clean, _ = run(spark, pages)
    assert {r["bot_reason"] for r in clean} == {"pages without assets"}
    clean, _ = run(spark, pages[:4] + [line(**{"x-edge-request-id": "a", "cs-uri-stem": "/img/p1.svg"})])
    assert {r["bot_class"] for r in clean} == {"human"}


def test_content_groups(spark):
    paths = {"/": "home", "/variants/b/index.html": "home", "/api/checkout": "checkout", "/api/products": "api",
             "/img/p1.svg": "asset", "/insights/": "insights", "/nope": "other"}
    clean, _ = run(spark, [line(**{"cs-uri-stem": p, "x-edge-request-id": p}) for p in paths])
    assert {r["path"]: r["content_group"] for r in clean} == paths
