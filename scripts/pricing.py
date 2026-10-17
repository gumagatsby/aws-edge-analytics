"""Fetch CloudFront data-transfer-out prices per pricing region from the AWS Pricing API.

Writes seeds/cloudfront_prices.csv: the first-tier (first 10 TB a month) price per GB
for each CloudFront pricing region, with the date it was fetched. The cost model
in sql/ joins request bytes to this table.

    python scripts/pricing.py
"""
import csv
import datetime
import json
import pathlib
import subprocess

OUT = pathlib.Path(__file__).resolve().parent.parent / "seeds" / "cloudfront_prices.csv"


def products(**filters):
    args = ["aws", "pricing", "get-products", "--region", "us-east-1", "--service-code", "AmazonCloudFront",
            "--max-results", "100", "--output", "json"]
    for key, value in filters.items():
        args += ["--filters", f"Type=TERM_MATCH,Field={key},Value={value}"]
    token = None
    while True:
        out = json.loads(subprocess.run(args + (["--next-token", token] if token else []),
                                        capture_output=True, text=True, check=True).stdout)
        for item in out["PriceList"]:
            yield json.loads(item)
        token = out.get("NextToken")
        if not token:
            return


def main():
    rows = {}
    for product in products(transferType="CloudFront Outbound"):
        attrs = product["product"]["attributes"]
        region = attrs.get("fromLocation")
        for term in product["terms"].get("OnDemand", {}).values():
            for dim in term["priceDimensions"].values():
                if dim["unit"] == "GB" and dim["beginRange"] == "0" and "USD" in dim["pricePerUnit"]:
                    rows[region] = (float(dim["pricePerUnit"]["USD"]), dim["description"])
    OUT.parent.mkdir(exist_ok=True)
    today = datetime.date.today().isoformat()
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pricing_region", "usd_per_gb_first_10tb", "description", "fetched"])
        for region, (usd, desc) in sorted(rows.items()):
            w.writerow([region, usd, desc, today])
    for region, (usd, _) in sorted(rows.items()):
        print(f"{region:20} ${usd}/GB")


if __name__ == "__main__":
    main()
