"""Compare the platform's reports with the answers planted in the synthetic logs.

Reads the report tables as the analyst role (the people the reports are for) and
truth.json from the generator. Tolerances are fixed here, before the comparison is
run, and printed with each result (brief, success criterion 2).

    python scripts/check_truth.py docs/evidence/truth.json
"""
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from verify import athena, check, outputs, results, session_for  # noqa: E402

# Tolerances, decided in advance.
BYTES_REL = 0.0001        # bytes by country: within 0.01% (float rounding only)
BOT_SHARE_PP = 0.5        # bot share: within 0.5 percentage points of the planted share


def main(truth_path):
    truth = json.loads(pathlib.Path(truth_path).read_text())
    days, plan = truth["days"], truth["generated_with"]
    out = outputs()
    db, wg, analyst = out["curated_db"], out["people_workgroups"]["analyst"], session_for(out["analyst_role_arn"])
    first, last = min(days), max(days)

    def q(sql):
        rows, err = athena(sql, wg, analyst)
        if err:
            raise SystemExit(f"query failed: {err}\n{sql}")
        return rows

    where = f"source = 'synthetic' AND day BETWEEN DATE '{first}' AND DATE '{last}'"
    by_day = lambda sql: {r[0]: r[1:] for r in q(sql)}  # noqa: E731

    totals = by_day(f"SELECT CAST(day AS varchar), sum(requests) FROM {db}.agg_edge_daily WHERE {where} GROUP BY 1")
    bots = by_day(f"SELECT CAST(day AS varchar), sum(requests) FILTER (WHERE bot_class = 'known_bot'), "
                  f"sum(requests) FILTER (WHERE bot_class = 'suspected_bot'), sum(requests) "
                  f"FROM {db}.agg_bots_daily WHERE {where} GROUP BY 1")
    ab = q(f"SELECT CAST(day AS varchar), ab_group, visitors, converters FROM {db}.agg_ab_daily WHERE {where}")
    broken = by_day(f"SELECT CAST(day AS varchar), sum(requests) FROM {db}.agg_errors_daily "
                    f"WHERE {where} AND status = 404 AND path = '/products/13.html' GROUP BY 1")
    incident = by_day(f"SELECT CAST(day AS varchar), sum(requests) FROM {db}.agg_errors_daily "
                      f"WHERE {where} AND status = 502 AND edge_code = '{plan['api_incident']['edge']}' GROUP BY 1")
    # truth.json counts bytes for human visitors only, so the comparison is human traffic.
    countries = q(f"SELECT CAST(day AS varchar), country, sum(bytes_sent) FROM {db}.fact_request "
                  f"WHERE {where} AND bot_class = 'human' GROUP BY 1, 2")

    print(f"{'day':10}  {'requests':>17}  {'bot share % (planted)':>22}  {'404 broken':>13}  {'502 incident':>13}")
    for day in sorted(days):
        t = days[day]
        planted_bots = (t["known_bot_requests"] + t["scripted_requests"] + t["stealth_requests"]) / t["total_requests"]
        known, suspected, total = (int(x or 0) for x in bots.get(day, (0, 0, 0)))
        found_share = (known + suspected) / total if total else 0
        print(f"{day}  {int(totals.get(day, [0])[0]):>8,} ({t['total_requests']:>7,})  "
              f"{found_share * 100:>9.2f} ({planted_bots * 100:>6.2f})  "
              f"{int(broken.get(day, [0])[0] or 0):>5} ({t['broken_link']:>5})  "
              f"{int(incident.get(day, [0])[0] or 0):>5} ({t['api_502']:>5})")

    check("every synthetic request counted, every day",
          all(int(totals.get(d, [0])[0]) == days[d]["total_requests"] for d in days))
    check("known crawlers found exactly, every day",
          all(int((bots.get(d) or [0])[0] or 0) == days[d]["known_bot_requests"] for d in days))
    worst = max(abs((int(bots[d][0] or 0) + int(bots[d][1] or 0)) / int(bots[d][2])
                    - (days[d]["known_bot_requests"] + days[d]["scripted_requests"] + days[d]["stealth_requests"])
                    / days[d]["total_requests"]) * 100 for d in days if d in bots)
    check(f"bot share within {BOT_SHARE_PP} percentage points of planted, every day", worst <= BOT_SHARE_PP,
          f"largest gap {worst:.2f} pp")
    check("broken link 404s found exactly, every day",
          all(int(broken.get(d, [0])[0] or 0) == days[d]["broken_link"] for d in days))
    check(f"API incident 502s at {plan['api_incident']['edge']} found exactly, every day",
          all(int(incident.get(d, [0])[0] or 0) == days[d]["api_502"] for d in days))

    worst = 0.0
    for day, country, sent in countries:
        planted = days[day]["bytes_by_country"].get(country)
        worst = max(worst, abs(int(sent) - planted) / planted if planted else 1.0)
    check(f"human bytes by country within {BYTES_REL:.2%}, every day and country", worst <= BYTES_REL,
          f"largest gap {worst:.5%}")

    # The experiment: counts must match exactly; the effect is then judged against the plan.
    # A visitor is an IP and user agent pair, so two generated sessions that drew the same pair
    # are one visitor to the platform; truth.json records the distinct counts as well.
    found = {(d, g): (int(v), int(c)) for d, g, v, c in ab}
    exact = all(found.get((d, g)) == (days[d]["distinct_visitors"][g], days[d]["distinct_converters"][g])
                for d in days for g in "AB")
    shared = sum(days[d]["visitors"][g] - days[d]["distinct_visitors"][g] for d in days for g in "AB")
    check("experiment visitors and converters found exactly, every day and group", exact,
          f"{shared} generated session(s) shared an IP and user agent with another")
    n = {g: sum(found.get((d, g), (0, 0))[0] for d in days) for g in "AB"}
    c = {g: sum(found.get((d, g), (0, 0))[1] for d in days) for g in "AB"}
    p = {g: c[g] / n[g] for g in "AB"}
    diff = p["B"] - p["A"]
    se = math.sqrt(p["A"] * (1 - p["A"]) / n["A"] + p["B"] * (1 - p["B"]) / n["B"])
    low, high = diff - 1.96 * se, diff + 1.96 * se
    planted = plan["conversion_rate"]["B"] - plan["conversion_rate"]["A"]
    print(f"experiment over {len(days)} days: A {c['A']}/{n['A']} = {p['A']:.3%}, B {c['B']}/{n['B']} = {p['B']:.3%}; "
          f"difference {diff * 100:.2f} pp, 95% interval {low * 100:.2f} to {high * 100:.2f} pp; planted {planted * 100:.2f} pp")
    check("experiment: B better than A at 95% confidence", low > 0)
    check("experiment: planted effect lies inside the 95% interval", low <= planted <= high)

    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main(sys.argv[1])
