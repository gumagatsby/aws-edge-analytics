import json

from handler import handler


def call(path, **query):
    r = handler({"rawPath": path, "queryStringParameters": query or None}, None)
    return r["statusCode"], json.loads(r["body"])


def test_products_and_checkout():
    assert call("/api/health") == (200, {"ok": True})
    status, products = call("/api/products")
    assert status == 200 and len(products) == 12
    assert call("/api/products/3")[1]["name"] == "Canvas tote"
    status, order = call("/api/checkout", sku="3")
    assert status == 200 and order["status"] == "confirmed"


def test_errors():
    assert call("/api/products/99")[0] == 404
    assert call("/api/checkout", sku="nope")[0] == 400
    assert call("/api/nothing")[0] == 404
