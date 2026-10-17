"""Generate the storefront's static pages into site/.

Two homepage designs (A and B, for the experiment), twelve product pages, one
stylesheet and a product image each. Plain on purpose: the site exists to be
served and logged, not to be judged on looks.

    python scripts/build_site.py
"""
import html
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "api"))
from handler import PRODUCTS  # noqa: E402  (one catalogue for the site and the API)

SITE = pathlib.Path(__file__).resolve().parent.parent / "site"
COLOURS = ["#5b6b5a", "#8a6f4e", "#4f6475", "#7a5560", "#6a6a6a", "#4e6b62"]


def page(title, body, depth=0):
    up = "../" * depth
    return f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} | Example Outfitters</title><link rel="stylesheet" href="/css/site.css"></head>
<body><header><a class="brand" href="/">Example Outfitters</a><nav><a href="/">Shop</a> <a href="/products/1.html">New in</a></nav></header>
<main>{body}</main><footer>Example Outfitters is a fictional shop used to generate CloudFront traffic for a portfolio project.</footer></body></html>
"""


def price(p):
    return f"£{p['price_pence'] / 100:.2f}"


def card(p):
    return (f'<a class="card" href="/products/{p["id"]}.html"><img src="/img/p{p["id"]}.svg" alt="" width="240" height="240">'
            f'<span>{html.escape(p["name"])}</span><span class="price">{price(p)}</span></a>')


def main():
    products = list(PRODUCTS.values())
    (SITE / "variants" / "b").mkdir(parents=True, exist_ok=True)
    (SITE / "products").mkdir(exist_ok=True)
    (SITE / "img").mkdir(exist_ok=True)
    (SITE / "css").mkdir(exist_ok=True)

    # Design A: the current homepage. A large banner, then six products.
    (SITE / "index.html").write_text(page("Shop", f"""
<section class="banner"><h1>Clothes that last</h1><p>Made in small batches, repaired for free.</p>
<a class="button" href="/products/1.html">Shop the collection</a></section>
<section class="grid">{''.join(card(p) for p in products[:6])}</section>"""))

    # Design B: the redesign under test. Products first, delivery promise up front.
    (SITE / "variants" / "b" / "index.html").write_text(page("Shop", f"""
<p class="notice">Free UK delivery and returns on every order</p>
<section class="grid wide">{''.join(card(p) for p in products)}</section>""", depth=2))

    for p in products:
        (SITE / "products" / f"{p['id']}.html").write_text(page(p["name"], f"""
<article class="product"><img src="/img/p{p['id']}.svg" alt="" width="480" height="480">
<div><h1>{html.escape(p['name'])}</h1><p class="price">{price(p)}</p>
<a class="button" href="/api/checkout?sku={p['id']}">Buy now</a></div></article>""", depth=1))
        colour = COLOURS[int(p["id"]) % len(COLOURS)]
        (SITE / "img" / f"p{p['id']}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240"><rect width="240" height="240" fill="#efece6"/>'
            f'<rect x="60" y="50" width="120" height="140" rx="6" fill="{colour}"/></svg>')

    (SITE / "css" / "site.css").write_text("""body{margin:0;font:16px/1.5 Georgia,serif;color:#222;background:#faf9f6}
header,footer{display:flex;justify-content:space-between;padding:16px 24px;border-bottom:1px solid #ddd}
footer{border:0;border-top:1px solid #ddd;font-size:13px;color:#666;margin-top:48px}
a{color:inherit}.brand{font-weight:bold;text-decoration:none}nav a{margin-left:16px}
main{max-width:1040px;margin:0 auto;padding:0 16px}
.banner{padding:72px 0 40px}.banner h1{font-size:44px;margin:0 0 8px}
.button{display:inline-block;margin-top:16px;padding:10px 18px;background:#222;color:#fff;text-decoration:none}
.notice{margin:24px 0 0;padding:10px 0;border-bottom:1px solid #222}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:24px;margin:32px 0}
.card{display:flex;flex-direction:column;text-decoration:none}.card img{width:100%;height:auto}
.price{color:#555}.product{display:grid;grid-template-columns:1fr 1fr;gap:32px;margin:40px 0}
.product img{width:100%;height:auto}@media(max-width:640px){.product{grid-template-columns:1fr}}
""")
    (SITE / "robots.txt").write_text("User-agent: *\nAllow: /\n")
    print(f"{len(list(SITE.rglob('*.*')))} files in {SITE}")


if __name__ == "__main__":
    main()
