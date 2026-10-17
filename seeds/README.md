# Seed data

| File | What | Source |
|---|---|---|
| `cloudfront_prices.csv` | Data-transfer-out price per GB, first 10 TB a month, per CloudFront pricing region | AWS Pricing API, fetched by `scripts/pricing.py` (date in the file) |
| `edge_locations.csv` | Edge location code (IATA airport code) to city, country, pricing region and the cheapest price class that includes it | Compiled for this project. CloudFront names edge locations by IATA code but publishes no machine-readable mapping. Price-class membership follows the CloudFront API reference: 100 is the US, Canada, Europe and Israel; 200 adds Africa, the Middle East and Asia; All adds South America and Australia. |

An edge code missing from `edge_locations.csv` is not an error: it is reported as `Unknown` and counted, so the list can be extended when a new code appears.
