"""Generate synthetic CloudFront access logs with known, planted answers.

The logs use CloudFront's exact W3C layout and field list, so the pipeline
processes them exactly as it processes real logs. Because the true answers are
planted, the platform's output can be checked against them (brief, success
criterion 2). Every row is marked synthetic: the files go under synthetic/ and the
pipeline labels their source.

What is planted, all written to truth.json:
  - a global audience, served from edge locations in every price-class tier
  - bot traffic: known crawlers, scripted clients and one scraper that fakes a browser
  - a homepage experiment: design B converts better than design A by a set amount
  - tracking parameters on a share of landing pages, which fragment the cache until
    the edge function removes them (from a set day onwards)
  - a broken product link (404s) and an API incident at one edge location (502s)

IP addresses come from 100.64.0.0/10 (shared address space, RFC 6598) and
2001:db8::/32 (documentation, RFC 3849), so none belongs to a real person.

    python traffic/synthetic.py --start 2026-10-10 --days 7 --out out/synthetic
    python traffic/synthetic.py ... --bucket <raw bucket>   # upload instead
"""
import argparse
import datetime as dt
import gzip
import io
import ipaddress
import json
import pathlib
import random
import string
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "glue"))
from edge_etl.fields import FIELDS  # noqa: E402  (one field list for generator and parser)

# country: (weight, [edge codes], asn, miss latency range in ms to the London origin)
AUDIENCE = {
    "GB": (28, ["LHR", "MAN"], 2856, (18, 35)),
    "US": (18, ["IAD", "JFK", "ORD", "DFW", "LAX", "SFO", "SEA", "ATL"], 7922, (85, 160)),
    "DE": (7, ["FRA", "MUC"], 3320, (30, 50)),
    "FR": (5, ["CDG", "MRS"], 3215, (28, 45)),
    "NL": (3, ["AMS"], 1136, (25, 40)),
    "IE": (3, ["DUB"], 5466, (25, 40)),
    "CA": (3, ["YTO", "YUL", "YVR"], 812, (90, 170)),
    "IN": (6, ["BOM", "DEL", "MAA", "BLR"], 55836, (140, 230)),
    "JP": (4, ["NRT", "KIX"], 2516, (210, 270)),
    "SG": (3, ["SIN"], 9506, (160, 220)),
    "AE": (3, ["DXB", "FJR"], 5384, (110, 160)),
    "ZA": (2, ["JNB", "CPT"], 3741, (170, 230)),
    "AU": (5, ["SYD", "MEL"], 1221, (260, 330)),
    "NZ": (1, ["AKL"], 9500, (280, 350)),
    "BR": (5, ["GRU", "GIG"], 28573, (190, 260)),
    "AR": (1, ["EZE"], 7303, (220, 290)),
    "IL": (1, ["TLV"], 8551, (60, 90)),
    "KR": (2, ["ICN"], 4766, (230, 290)),
}
EDGE_SUFFIX = ["50-P1", "52-C1", "53-P2", "56-P3", "61-C2"]

BROWSERS = {
    "desktop": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.{m} Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{v}.0) Gecko/20100101 Firefox/{v}.0",
    ],
    "mobile": [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_{m} like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.{m} Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Mobile Safari/537.36",
    ],
    "tablet": ["Mozilla/5.0 (iPad; CPU OS 18_{m} like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.{m} Mobile/15E148 Safari/604.1"],
}
KNOWN_BOTS = [
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)",
    "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)",
]
SCRIPTED = ["python-requests/2.32.3", "Go-http-client/2.0", "curl/8.7.1", "okhttp/4.12.0"]

PRODUCTS = [str(i) for i in range(1, 13)]
SIZES = {"html": (2600, 4200), "css": (1100, 1300), "photo": (90_000, 320_000), "json": (900, 2400)}
TTL_S = 3600

# The planted answers.
CONVERSION = {"A": 0.030, "B": 0.036}           # B converts 20% better (relative)
TRACKING_SHARE = 0.35                             # landing pages carrying utm_/gclid parameters
BROKEN_LINK_SHARE = 0.015                         # product views that hit the dead /products/13.html
API_INCIDENT = {"edge": "SIN", "day_index": 3, "error_rate": 0.25}


def fnv_group(text):
    """Same FNV-1a as edge/viewer_request.js, so synthetic visitors split as real ones do."""
    h = 0x811C9DC5
    for ch in text:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return "A" if h % 2 == 0 else "B"


class Generator:
    def __init__(self, seed, start, days, visitors_per_day, normalise_from):
        self.rng = random.Random(seed)
        self.start, self.days = start, days
        self.visitors_per_day = visitors_per_day
        self.normalise_from = normalise_from
        self.cache = {}
        self.truth = {"generated_with": {"seed": seed, "start": str(start), "days": days,
                                         "visitors_per_day": visitors_per_day,
                                         "normalisation_from_day_index": normalise_from,
                                         "conversion_rate": CONVERSION, "tracking_share": TRACKING_SHARE,
                                         "broken_link_share": BROKEN_LINK_SHARE, "api_incident": API_INCIDENT},
                      "days": {}}

    # --- helpers ------------------------------------------------------------
    def ip(self):
        if self.rng.random() < 0.15:
            return str(ipaddress.IPv6Address(int(ipaddress.IPv6Address("2001:db8::")) + self.rng.getrandbits(96)))
        return str(ipaddress.IPv4Address(int(ipaddress.IPv4Address("100.64.0.0")) + self.rng.getrandbits(22)))

    def request_id(self):
        return "".join(self.rng.choices(string.ascii_letters + string.digits + "_-", k=54)) + "=="

    def edge(self, country):
        return self.rng.choice(AUDIENCE[country][1]) + self.rng.choice(EDGE_SUFFIX)

    def cached(self, edge, key, ts):
        """A per-edge cache with a one-hour TTL: the first request for a key misses."""
        k = (edge[:3], key)
        expiry = self.cache.get(k)
        if expiry and expiry > ts:
            return True
        self.cache[k] = ts + TTL_S
        return False

    # --- one log line ----------------------------------------------------------
    def line(self, *, ts, visitor, path, query="", cache_query=None, status=200, kind="html", group=None,
             new=False, stripped=0, cacheable=True):
        # The log records the query the visitor sent; the cache key uses it only if the
        # edge function left it in place (cache_query).
        country, ip, ua, edge = visitor["country"], visitor["ip"], visitor["ua"], visitor["edge"]
        cache_query = query if cache_query is None else cache_query
        key = path + ("?" + cache_query if cache_query else "")
        if cacheable and status == 200:
            hit = self.cached(edge, key, ts)
        else:
            hit = False
        lo, hi = AUDIENCE[country][3]
        if hit:
            ttfb = self.rng.uniform(0.002, 0.018)
            result = "Hit"
        else:
            ttfb = self.rng.uniform(lo, hi) / 1000 + (0.012 if path.startswith("/api/") else 0.004)
            result = "Miss" if status < 400 else "Error"
        size = self.rng.randint(*SIZES[kind]) if status < 400 else 380
        content_type = {"html": "text/html; charset=utf-8", "css": "text/css", "photo": "image/jpeg",
                        "json": "application/json"}[kind]
        log_data = "-"
        if group:
            log_data = f"ab%3D{group}" + ("%3Bnew%3D1" if new else "") + (f"%3Bstripped%3D{stripped}" if stripped else "")
        t = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
        values = {
            "date": t.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M:%S"), "timestamp(ms)": str(int(ts * 1000)),
            "x-edge-location": edge, "sc-bytes": str(size + 420), "c-ip": ip, "cs-method": "GET",
            "cs(Host)": "dexample.cloudfront.net", "cs-uri-stem": path, "sc-status": str(status),
            "cs(Referer)": visitor.get("referer", "-"), "cs(User-Agent)": ua.replace(" ", "%20"),
            "cs-uri-query": query or "-", "cs(Cookie)": "-", "x-edge-result-type": result,
            "x-edge-request-id": self.request_id(), "x-host-header": "shop.example.com", "cs-protocol": "https",
            "cs-bytes": str(self.rng.randint(180, 520)), "time-taken": f"{ttfb + 0.001:.3f}", "x-forwarded-for": "-",
            "ssl-protocol": "TLSv1.3", "ssl-cipher": "TLS_AES_128_GCM_SHA256", "x-edge-response-result-type": result,
            "cs-protocol-version": "HTTP/2.0", "time-to-first-byte": f"{ttfb:.3f}", "x-edge-detailed-result-type": result,
            "sc-content-type": content_type, "sc-content-len": str(size), "c-country": country,
            "asn": str(AUDIENCE[country][2]), "cache-behavior-path-pattern": "/api/*" if path.startswith("/api/") else "*",
            "viewer-request-log-data": log_data,
        }
        return "\t".join(values[f] for f in FIELDS)

    # --- visitors ------------------------------------------------------------
    def human(self, day_start, day_index, tally):
        country = self.rng.choices(list(AUDIENCE), weights=[a[0] for a in AUDIENCE.values()])[0]
        device = self.rng.choices(["mobile", "desktop", "tablet"], weights=[55, 40, 5])[0]
        ua = self.rng.choice(BROWSERS[device]).format(v=self.rng.randint(128, 141), m=self.rng.randint(0, 6))
        visitor = {"country": country, "ip": self.ip(), "ua": ua, "edge": self.edge(country)}
        group = fnv_group(f"{visitor['ip']}|{ua}")
        normalise = day_index >= self.normalise_from
        ts = day_start + self.rng.uniform(0, 86400 - 900)
        out = []

        query = ""
        if self.rng.random() < TRACKING_SHARE:
            query = (f"utm_source={self.rng.choice(['newsletter', 'instagram', 'google'])}"
                     f"&utm_campaign=autumn{self.rng.randint(1, 40)}")
            if self.rng.random() < 0.4:
                query += f"&gclid={self.rng.getrandbits(48):x}"
        stripped = query.count("=") if (query and normalise) else 0
        home = "/index.html" if group == "A" else "/variants/b/index.html"
        out.append(self.line(ts=ts, visitor=visitor, path=home, query=query, cache_query="" if normalise else query,
                             group=group, new=True, stripped=stripped))
        out.append(self.line(ts=ts + 0.2, visitor=visitor, path="/css/site.css", kind="css", group=group))
        for p in self.rng.sample(PRODUCTS, 6 if group == "A" else 12)[:4]:
            out.append(self.line(ts=ts + 0.3, visitor=visitor, path=f"/img/p{p}.jpg", kind="photo", group=group))

        viewed = self.rng.sample(PRODUCTS, self.rng.randint(1, 4))
        t = ts + self.rng.uniform(5, 40)
        for p in viewed:
            if self.rng.random() < BROKEN_LINK_SHARE:
                out.append(self.line(ts=t, visitor=visitor, path="/products/13.html", status=404, group=group))
                tally["broken_link"] += 1
            out.append(self.line(ts=t, visitor=visitor, path=f"/products/{p}.html", group=group))
            out.append(self.line(ts=t + 0.2, visitor=visitor, path=f"/img/p{p}.jpg", kind="photo", group=group))
            api_status = 200
            if visitor["edge"].startswith(API_INCIDENT["edge"]) and day_index == API_INCIDENT["day_index"] \
                    and self.rng.random() < API_INCIDENT["error_rate"]:
                api_status = 502
                tally["api_502"] += 1
            out.append(self.line(ts=t + 0.4, visitor=visitor, path=f"/api/products/{p}", kind="json",
                                 status=api_status, cacheable=False, group=group))
            t += self.rng.uniform(8, 60)

        converted = self.rng.random() < CONVERSION[group]
        if converted:
            out.append(self.line(ts=t, visitor=visitor, path="/api/checkout", query=f"sku={viewed[0]}", kind="json",
                                 cacheable=False, group=group))
        tally["visitors"][group] += 1
        tally["converters"][group] += int(converted)
        # Visitors are identified by IP and user agent, as on the real site. Two sessions that
        # draw the same pair are one visitor to any platform, so the truth records that too.
        identity = (visitor["ip"], ua)
        self.identities[group].add(identity)
        if converted:
            self.converted_identities[group].add(identity)
        tally["human_requests"] += len(out)
        # Human visitors only: bot traffic is tallied by kind, not by country.
        tally["bytes_by_country"][country] = tally["bytes_by_country"].get(country, 0) + sum(
            int(l.split("\t")[FIELDS.index("sc-bytes")]) for l in out)
        return out

    def known_bot(self, day_start, tally):
        visitor = {"country": "US", "ip": self.ip(), "ua": self.rng.choice(KNOWN_BOTS), "edge": self.edge("US")}
        ts = day_start + self.rng.uniform(0, 86000)
        out = [self.line(ts=ts + i * self.rng.uniform(1, 4), visitor=visitor, path=f"/products/{p}.html")
               for i, p in enumerate(self.rng.sample(PRODUCTS, self.rng.randint(4, 12)))]
        tally["known_bot_requests"] += len(out)
        return out

    def scripted_bot(self, day_start, tally):
        country = self.rng.choice(["US", "DE", "SG", "IN"])
        visitor = {"country": country, "ip": self.ip(), "ua": self.rng.choice(SCRIPTED), "edge": self.edge(country)}
        ts = day_start + self.rng.uniform(0, 86000)
        out = [self.line(ts=ts + i * 0.5, visitor=visitor, path=f"/api/products/{self.rng.choice(PRODUCTS)}",
                         kind="json", cacheable=False) for i in range(self.rng.randint(20, 60))]
        tally["scripted_requests"] += len(out)
        return out

    def stealth_scraper(self, day_start, tally):
        """Browser user agent, but reads every product page and never loads a stylesheet or image."""
        visitor = {"country": "DE", "ip": self.ip(), "edge": self.edge("DE"),
                   "ua": BROWSERS["desktop"][0].format(v=139, m=0)}
        out = []
        for burst in range(6):
            ts = day_start + burst * 14000 + self.rng.uniform(0, 600)
            out += [self.line(ts=ts + i * 3, visitor=visitor, path=f"/products/{p}.html") for i, p in enumerate(PRODUCTS)]
        tally["stealth_requests"] += len(out)
        return out

    # --- days ----------------------------------------------------------------
    def day(self, day_index):
        day = self.start + dt.timedelta(days=day_index)
        day_start = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp()
        self.cache.clear()
        self.identities = {"A": set(), "B": set()}
        self.converted_identities = {"A": set(), "B": set()}
        tally = {"visitors": {"A": 0, "B": 0}, "converters": {"A": 0, "B": 0}, "human_requests": 0,
                 "known_bot_requests": 0, "scripted_requests": 0, "stealth_requests": 0, "broken_link": 0,
                 "api_502": 0, "bytes_by_country": {}}
        lines = []
        for _ in range(self.visitors_per_day):
            lines += self.human(day_start, day_index, tally)
        for _ in range(self.visitors_per_day // 7):
            lines += self.known_bot(day_start, tally)
        for _ in range(self.visitors_per_day // 57):
            lines += self.scripted_bot(day_start, tally)
        lines += self.stealth_scraper(day_start, tally)

        stamp = FIELDS.index("timestamp(ms)")
        lines.sort(key=lambda l: int(l.split("\t", stamp + 1)[stamp]))
        total = len(lines)
        tally["total_requests"] = total
        tally["bot_share"] = round((tally["known_bot_requests"] + tally["scripted_requests"] + tally["stealth_requests"]) / total, 4)
        tally["distinct_visitors"] = {g: len(self.identities[g]) for g in "AB"}
        tally["distinct_converters"] = {g: len(self.converted_identities[g]) for g in "AB"}
        tally["conversion_observed"] = {g: round(tally["converters"][g] / max(tally["visitors"][g], 1), 4) for g in "AB"}
        tally["normalisation_on"] = day_index >= self.normalise_from
        self.truth["days"][str(day)] = tally
        return day, lines


HEADER = "#Version: 1.0\n#Fields: " + " ".join(FIELDS) + "\n"


def hourly_files(day, lines):
    """Split a day into one gzip file per UTC hour, in CloudFront's partition layout."""
    stamp = FIELDS.index("timestamp(ms)")
    by_hour = {}
    for l in lines:
        hour = dt.datetime.fromtimestamp(int(l.split("\t", stamp + 1)[stamp]) / 1000, dt.timezone.utc).hour
        by_hour.setdefault(hour, []).append(l)
    for hour, rows in sorted(by_hour.items()):
        key = (f"synthetic/distributionid=synthetic/year={day:%Y}/month={day:%m}/day={day:%d}/hour={hour:02d}/"
               f"synthetic.{day:%Y-%m-%d}-{hour:02d}.gz")
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
            gz.write((HEADER + "\n".join(rows) + "\n").encode())
        yield key, buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=dt.date.fromisoformat, required=True)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--visitors-per-day", type=int, default=12000)
    ap.add_argument("--normalise-from", type=int, default=4, help="day index from which tracking parameters are stripped")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--bucket")
    args = ap.parse_args()

    gen = Generator(args.seed, args.start, args.days, args.visitors_per_day, args.normalise_from)
    s3 = None
    if args.bucket:
        import boto3
        s3 = boto3.client("s3")
    for i in range(args.days):
        day, lines = gen.day(i)
        size = 0
        for key, body in hourly_files(day, lines):
            size += len(body)
            if s3:
                s3.put_object(Bucket=args.bucket, Key=key, Body=body)
            if args.out:
                path = args.out / key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
        t = gen.truth["days"][str(day)]
        print(f"{day}: {len(lines):,} requests, {size / 1e6:.1f} MB gzipped, bot share {t['bot_share']:.1%}, "
              f"conversion A {t['conversion_observed']['A']:.2%} B {t['conversion_observed']['B']:.2%}")
    truth = json.dumps(gen.truth, indent=2)
    if args.out:
        (args.out / "truth.json").write_text(truth)
    if s3:
        s3.put_object(Bucket=args.bucket, Key="synthetic/truth.json", Body=truth.encode())


if __name__ == "__main__":
    main()
