"""Storefront API behind CloudFront. A purchase is GET /api/checkout?sku=..., which is
the conversion event the A/B analysis counts in the access logs."""
import json
import uuid

PRODUCTS = {
    str(i): {"id": str(i), "name": name, "price_pence": price}
    for i, (name, price) in enumerate([
        ("Linen shirt", 4500), ("Wool jumper", 7900), ("Canvas tote", 1800), ("Leather belt", 3500),
        ("Rain jacket", 12500), ("Cotton socks", 900), ("Denim jeans", 6500), ("Silk scarf", 4200),
        ("Trail shoes", 9800), ("Baseball cap", 2200), ("Wool beanie", 1900), ("Chino shorts", 3900),
    ], start=1)
}


def respond(status, body):
    return {"statusCode": status, "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "body": json.dumps(body)}


def handler(event, context):
    path = event.get("rawPath", "")
    query = event.get("queryStringParameters") or {}
    if path == "/api/health":
        return respond(200, {"ok": True})
    if path == "/api/products":
        return respond(200, list(PRODUCTS.values()))
    if path.startswith("/api/products/"):
        product = PRODUCTS.get(path.rsplit("/", 1)[1])
        return respond(200, product) if product else respond(404, {"error": "No such product"})
    if path == "/api/checkout":
        product = PRODUCTS.get(query.get("sku", ""))
        if not product:
            return respond(400, {"error": "Unknown sku"})
        return respond(200, {"order_id": str(uuid.uuid4()), "sku": product["id"], "status": "confirmed"})
    return respond(404, {"error": "Not found"})
