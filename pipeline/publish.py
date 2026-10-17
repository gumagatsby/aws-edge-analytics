"""Build the dashboard's data file from the report tables.

Every figure on the dashboard comes from here, so the statistics live here too:
the A/B comparison (two-proportion z-test) and the price-class cost scenarios.
"""
import datetime as dt
import math

PRICE_CLASS_RANK = {"PriceClass_100": 1, "PriceClass_200": 2, "PriceClass_All": 3}
# Viewers outside a cheaper price class are served from its edge locations and billed at
# their rate; the lowest rate in every class is the US and Europe rate.
FALLBACK_REGION = "Europe"


def num(v, cast=float):
    return None if v is None else cast(v)


def ab_test(a_visitors, a_conv, b_visitors, b_conv):
    """Two-proportion z-test of B against A, with a 95% interval on the difference."""
    if min(a_visitors, b_visitors) == 0:
        return None
    pa, pb = a_conv / a_visitors, b_conv / b_visitors
    pooled = (a_conv + b_conv) / (a_visitors + b_visitors)
    se_pooled = math.sqrt(pooled * (1 - pooled) * (1 / a_visitors + 1 / b_visitors))
    z = (pb - pa) / se_pooled if se_pooled else 0.0
    p_value = math.erfc(abs(z) / math.sqrt(2))
    se = math.sqrt(pa * (1 - pa) / a_visitors + pb * (1 - pb) / b_visitors)
    return {"rate_a": pa, "rate_b": pb, "difference": pb - pa, "relative_lift": (pb - pa) / pa if pa else None,
            "ci95": [pb - pa - 1.96 * se, pb - pa + 1.96 * se], "z": z, "p_value": p_value,
            "significant": p_value < 0.05}


def price_class_scenarios(cost_rows, rates):
    """Monthly-equivalent cost of the observed traffic under each price class."""
    fallback = rates.get(FALLBACK_REGION)
    out = {}
    for cls, rank in PRICE_CLASS_RANK.items():
        total, moved_gb = 0.0, 0.0
        for r in cost_rows:
            gb, rate = r["gb"], r["usd_per_gb"] or fallback
            if PRICE_CLASS_RANK.get(r["price_class"], 3) <= rank:
                total += gb * rate
            else:
                total += gb * fallback
                moved_gb += gb
        out[cls] = {"usd": total, "gb_served_from_further_away": moved_gb}
    base = out["PriceClass_All"]["usd"]
    for v in out.values():
        v["saving_vs_all"] = (base - v["usd"]) / base if base else 0.0
    return out


def build(query, curated, clean):
    sources = [r["source"] for r in query(f"SELECT DISTINCT source FROM {curated}.agg_edge_daily ORDER BY 1")]
    rates = {r["pricing_region"]: float(r["usd_per_gb"]) for r in query(
        f"SELECT pricing_region, usd_per_gb FROM {clean}.seed_cloudfront_prices WHERE pricing_region <> 'Any'")}
    data = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "price_source": "AWS Pricing API, first 10 TB per month, list price", "sources": {}}

    for src in sources:
        where = f"source = '{src}'"
        daily = query(f"""
            SELECT day, sum(requests) AS requests, sum(gb) AS gb, sum(cacheable_requests) AS cacheable,
                   sum(cache_hits) AS hits, sum(bot_requests) AS bots, sum(errors_4xx) AS e4, sum(errors_5xx) AS e5
            FROM {curated}.agg_edge_daily WHERE {where} GROUP BY 1 ORDER BY 1""")
        edges = query(f"""
            SELECT f.edge_code, coalesce(e.city, 'Unknown') AS city, coalesce(e.country_code, '--') AS country,
                   coalesce(e.pricing_region, 'Unknown') AS pricing_region, coalesce(e.price_class, 'Unknown') AS price_class,
                   count(*) AS requests, sum(f.bytes_sent) / 1e9 AS gb,
                   count_if(f.cacheable) AS cacheable, count_if(f.cacheable AND f.is_cache_hit) AS hits,
                   approx_percentile(f.ttfb_ms, 0.5) FILTER (WHERE f.is_cache_hit) AS ttfb_hit_p50,
                   approx_percentile(f.ttfb_ms, 0.5) FILTER (WHERE NOT f.is_cache_hit AND f.status < 400) AS ttfb_miss_p50,
                   approx_percentile(f.ttfb_ms, 0.9) FILTER (WHERE NOT f.is_cache_hit AND f.status < 400) AS ttfb_miss_p90,
                   count_if(f.status >= 500) AS e5
            FROM {curated}.fact_request f LEFT JOIN {curated}.dim_edge_location e ON e.edge_code = f.edge_code
            WHERE f.{where} GROUP BY 1, 2, 3, 4, 5 ORDER BY requests DESC""")
        countries = query(f"""
            SELECT country, sum(requests) AS requests, sum(human_requests) AS humans, sum(gb) AS gb,
                   sum(cacheable_requests) AS cacheable, sum(cache_hits) AS hits
            FROM {curated}.agg_country_daily WHERE {where} GROUP BY 1 ORDER BY requests DESC""")
        ab_rows = {r["ab_group"]: r for r in query(f"""
            SELECT ab_group, sum(visitors) AS visitors, sum(converters) AS converters
            FROM {curated}.agg_ab_daily WHERE {where} GROUP BY 1""")}
        bots = query(f"""
            SELECT bot_class, bot_reason, sum(requests) AS requests, sum(gb) AS gb
            FROM {curated}.agg_bots_daily WHERE {where} GROUP BY 1, 2 ORDER BY requests DESC""")
        errors = query(f"""
            SELECT status, path, edge_code, day, sum(requests) AS requests
            FROM {curated}.agg_errors_daily WHERE {where} GROUP BY 1, 2, 3, 4 ORDER BY requests DESC LIMIT 15""")
        cache = query(f"""
            SELECT day, arrived_with_tracking, normalised, sum(cacheable_requests) AS cacheable, sum(cache_hits) AS hits
            FROM {curated}.agg_cache_daily WHERE {where} AND content_group = 'home' GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""")
        cost = query(f"""
            SELECT pricing_region, price_class, sum(gb) AS gb, max(usd_per_gb) AS usd_per_gb, sum(usd) AS usd
            FROM {curated}.agg_cost_daily WHERE {where} GROUP BY 1, 2 ORDER BY usd DESC""")

        total = sum(int(d["requests"]) for d in daily)
        bot_total = sum(int(b["requests"]) for b in bots if b["bot_class"] != "human")
        a, b = ab_rows.get("A"), ab_rows.get("B")
        cost_rows = [{"pricing_region": c["pricing_region"], "price_class": c["price_class"], "gb": float(c["gb"] or 0),
                      "usd_per_gb": num(c["usd_per_gb"]), "usd": float(c["usd"] or 0)} for c in cost]
        data["sources"][src] = {
            "daily": [{"day": d["day"], "requests": int(d["requests"]), "gb": float(d["gb"]),
                       "hit_ratio": int(d["hits"]) / int(d["cacheable"]) if int(d["cacheable"]) else None,
                       "bot_share": int(d["bots"]) / int(d["requests"]), "errors_4xx": int(d["e4"]),
                       "errors_5xx": int(d["e5"])} for d in daily],
            "totals": {"requests": total, "gb": sum(float(d["gb"]) for d in daily),
                       "bot_share": bot_total / total if total else None, "days": len(daily)},
            "edges": [{"edge": e["edge_code"], "city": e["city"], "country": e["country"],
                       "pricing_region": e["pricing_region"], "price_class": e["price_class"],
                       "requests": int(e["requests"]), "gb": float(e["gb"]),
                       "hit_ratio": int(e["hits"]) / int(e["cacheable"]) if int(e["cacheable"]) else None,
                       "ttfb_hit_p50_ms": num(e["ttfb_hit_p50"]), "ttfb_miss_p50_ms": num(e["ttfb_miss_p50"]),
                       "ttfb_miss_p90_ms": num(e["ttfb_miss_p90"]), "errors_5xx": int(e["e5"])} for e in edges],
            "countries": [{"country": c["country"], "requests": int(c["requests"]), "human_requests": int(c["humans"]),
                           "gb": float(c["gb"]),
                           "hit_ratio": int(c["hits"]) / int(c["cacheable"]) if int(c["cacheable"]) else None}
                          for c in countries],
            "ab": {"groups": {g: {"visitors": int(r["visitors"]), "converters": int(r["converters"])}
                              for g, r in ab_rows.items()},
                   "test": ab_test(int(a["visitors"]), int(a["converters"]), int(b["visitors"]), int(b["converters"]))
                   if a and b else None},
            "bots": [{"class": r["bot_class"], "reason": r["bot_reason"], "requests": int(r["requests"]),
                      "share": int(r["requests"]) / total if total else None} for r in bots],
            "errors": [{"status": int(e["status"]), "path": e["path"], "edge": e["edge_code"], "day": e["day"],
                        "requests": int(e["requests"])} for e in errors],
            "cache": [{"day": c["day"], "arrived_with_tracking": c["arrived_with_tracking"] == "true",
                       "normalised": c["normalised"] == "true", "cacheable": int(c["cacheable"]),
                       "hit_ratio": int(c["hits"]) / int(c["cacheable"]) if int(c["cacheable"]) else None} for c in cache],
            "cost": {"by_region": cost_rows, "total_usd": sum(r["usd"] for r in cost_rows),
                     "price_classes": price_class_scenarios(cost_rows, rates)},
        }

    data["pipeline"] = {
        "runs": query(f"""SELECT day, source, raw_lines, clean_rows, quarantined_rows, balanced,
                              CAST(finished_at AS varchar) AS finished_at
                           FROM {clean}.run_audit ORDER BY day DESC, source LIMIT 60"""),
        "quarantine": query(f"SELECT day, source, reason, count(*) AS n FROM {clean}.quarantine GROUP BY 1, 2, 3 ORDER BY 1 DESC"),
    }
    return data
