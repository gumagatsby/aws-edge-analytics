"""Send real traffic through CloudFront: simulated shoppers and bots.

Standard library only, so it runs anywhere, including GitHub Actions runners in the
US (a second real edge location). Each shopper keeps its own cookies, so CloudFront
assigns and keeps an A/B group exactly as it would for a browser. The response
headers show which edge location served each request; a summary is printed.

    python traffic/real.py --base-url https://dxxxx.cloudfront.net --visitors 300
"""
import argparse
import collections
import concurrent.futures as cf
import http.cookiejar
import random
import re
import threading
import time
import urllib.error
import urllib.request

BROWSERS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.{m} Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_{m} like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.{m} Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Mobile Safari/537.36",
]
CRAWLER = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
CONVERSION = {"A": 0.030, "B": 0.036}
TRACKING_SHARE = 0.35

stats = collections.Counter()
pops = collections.Counter()
lock = threading.Lock()


def fetch(opener, url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        with opener.open(req, timeout=20) as r:
            body = r.read()
            status, pop, cache = r.status, r.headers.get("x-amz-cf-pop", "?"), r.headers.get("x-cache", "?")
    except urllib.error.HTTPError as e:
        body, status, pop, cache = b"", e.code, e.headers.get("x-amz-cf-pop", "?"), e.headers.get("x-cache", "?")
    except Exception:
        with lock:
            stats["network_errors"] += 1
        return 0, b""
    with lock:
        stats[f"status_{status}"] += 1
        stats["requests"] += 1
        stats["cache_hit" if cache.startswith("Hit") else "cache_other"] += 1
        pops[pop[:3]] += 1
    return status, body


def shopper(base, rng):
    ua = rng.choice(BROWSERS).format(v=rng.randint(128, 141), m=rng.randint(0, 6))
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    query = ""
    if rng.random() < TRACKING_SHARE:
        query = f"?utm_source={rng.choice(['newsletter', 'instagram', 'google'])}&utm_campaign=autumn{rng.randint(1, 40)}"
    _, home = fetch(opener, base + "/" + query, ua)
    group = "B" if b'class="notice"' in home else "A"
    fetch(opener, base + "/css/site.css", ua)
    for img in sorted(set(re.findall(rb'src="(/img/p\d+\.svg)"', home)))[:4]:
        fetch(opener, base + img.decode(), ua)
    viewed = rng.sample(range(1, 13), rng.randint(1, 3))
    for p in viewed:
        time.sleep(rng.uniform(0.05, 0.3))
        fetch(opener, f"{base}/products/{p}.html", ua)
        fetch(opener, f"{base}/img/p{p}.svg", ua)
        fetch(opener, f"{base}/api/products/{p}", ua)
    converted = rng.random() < CONVERSION[group]
    if converted:
        fetch(opener, f"{base}/api/checkout?sku={viewed[0]}", ua)
    with lock:
        stats[f"visitors_{group}"] += 1
        stats[f"converters_{group}"] += int(converted)


def crawler(base, rng):
    opener = urllib.request.build_opener()
    for p in rng.sample(range(1, 13), 8):
        fetch(opener, f"{base}/products/{p}.html", CRAWLER)
    with lock:
        stats["crawler_sessions"] += 1


def scraper(base, rng):
    opener = urllib.request.build_opener()
    for _ in range(30):
        fetch(opener, f"{base}/api/products/{rng.randint(1, 12)}", "python-requests/2.32.3")
    with lock:
        stats["scraper_sessions"] += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--visitors", type=int, default=300)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    rng = random.Random(args.seed)
    jobs = [shopper] * args.visitors + [crawler] * max(1, args.visitors // 15) + [scraper] * max(1, args.visitors // 60)
    rng.shuffle(jobs)
    started = time.time()
    with cf.ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(lambda job: job(base, random.Random(rng.random())), jobs))
    print(f"{stats['requests']} requests in {time.time() - started:.0f} s")
    print("status:", {k: v for k, v in stats.items() if k.startswith("status_")})
    print("cache:", stats["cache_hit"], "hits,", stats["cache_other"], "other")
    print("visitors A/B:", stats["visitors_A"], stats["visitors_B"], " converters A/B:", stats["converters_A"], stats["converters_B"])
    print("bots: crawler sessions", stats["crawler_sessions"], " scraper sessions", stats["scraper_sessions"])
    print("edge locations:", dict(pops.most_common()))
    if stats["network_errors"]:
        print("network errors:", stats["network_errors"])


if __name__ == "__main__":
    main()
