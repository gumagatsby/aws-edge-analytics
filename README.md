# Edge analytics on AWS

[![ci](https://github.com/gumagatsby/aws-edge-analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/gumagatsby/aws-edge-analytics/actions/workflows/ci.yml)

A UK online retailer serves its site worldwide through Amazon CloudFront. CloudFront logs every request, and nobody reads the logs. This project turns those logs into answers: what the CDN costs by region, where the site is slow and why, whether the homepage redesign works, how much traffic is bots, and how to stop keeping visitors' IP addresses.

*The retailer is fictional. The AWS services, prices, measurements and failures are real.* The brief is in [docs/01-brief.md](docs/01-brief.md), every design choice with its alternatives and costs in [docs/02-options-and-decisions.md](docs/02-options-and-decisions.md), and every problem met during the build, with how it was solved, in [docs/04-build-log.md](docs/04-build-log.md).

## Architecture

```
 Visitors ──> CloudFront ──────────────────────────> S3 (static site, dashboard)   origin access control:
              │  viewer-request function:            Lambda function URL (API)    direct access returns 403
              │    A/B group, strip tracking params
              │  viewer-response function: A/B cookie
              │
              └─ standard logging v2 ─> S3 raw (eu-west-2, KMS, deleted after 7 days)
                                          │
  EventBridge Scheduler 05:00 UTC ─> Step Functions, one day at a time
                                          │
                     Glue 5.0 Spark job ──┤  parse 33 fields, quarantine bad lines with a reason,
                                          │  IP to /24 or /48, visitor id = HMAC (key in SSM),
                                          │  bot and device rules, Glue Data Quality, reconcile
                                          v
                               clean layer (Iceberg) ─> Athena SQL ─> curated star schema and
                                                                      report tables (Iceberg)
                                                                          │
                                                Lake Formation: analysts never see visitor_id
                                                                          │
                                             publish ─> dashboard JSON on the same distribution
  Failure at any step ─> SNS (KMS) ─> alert within minutes
```

Everything is Terraform, deployed from a laptop and from GitHub Actions with OIDC (no stored AWS keys), and destroyed after the build.

## What was built, and why this way

| Need | Choice | Why not the alternative |
|---|---|---|
| Logic at the edge | CloudFront Functions | Lambda@Edge is not available on the account's plan, and costs more per request |
| Log delivery | Standard logging v2 to S3 | Real-time logs need Kinesis, which the plan does not allow; a daily batch meets the 06:00 requirement |
| Processing personal data | One Glue Spark job | Keyed hashing, quarantine and parsing are awkward in SQL, and the key would appear in queries |
| Transformations the team owns | Athena SQL (no dbt) | The client's team knows SQL; one fewer tool to run |
| Orchestration | Step Functions | Managed Airflow costs about $244 a month idle; the budget is $10 for the whole build |
| Access control | Lake Formation column permissions | IAM alone cannot hide one column |

## Results

Verified from the platform's own tables, on two kinds of traffic: real CloudFront traffic (served from Johannesburg and Lagos from a laptop, and Chicago from GitHub's US runners) and a synthetic week of about 185,000 requests a day with answers planted in it.

**Cache key normalisation works.** Homepage visits that arrive with tracking parameters (`utm_source`, `gclid`) each created a separate cache entry. Stripping them at the edge:

| Homepage requests with tracking parameters | Normalisation off | Normalisation on |
|---|---|---|
| Real traffic, same 3,933 requests replayed | 1 of 99 cache hits (1.0%) | 99 of 99 (100%) |
| Synthetic week | 8.0% | 97.5% |

**The platform recovers every planted answer** ([evidence](docs/evidence/truth-recovery.txt)): every request, the bot share every day (about 12%, including a scraper posing as a browser), every broken-link 404, every 502 of a planted incident at one edge location, and human bytes by country exactly. The homepage experiment: design B converts at 3.52% against 2.89% for A, a 0.63 point lift with a 95% interval of 0.39 to 0.87 points; the planted lift was 0.60.

## Requirements, demonstrated

| | Requirement | Result | Evidence |
|---|---|---|---|
| N1 | No raw IP beyond the raw layer; raw logs deleted after 7 days | Pass: 85 text columns compared against every real raw address | [n1](docs/evidence/n1-no-raw-ip.txt) |
| N2 | Analysts see no visitor identifiers | Pass, 8 checks, including the engineer's query results | [n2](docs/evidence/n2-access.txt) |
| N3 | Raw rows = clean + quarantined, every run | Pass, every day | [n3](docs/evidence/n3-reconciliation.txt) |
| N4 | Re-processing a day gives identical tables | Pass: 11 tables, row counts and checksums, two days re-run | [n4](docs/evidence/n4-rerun.txt) |
| N5 | Failure alert within 15 minutes | Pass: 70 seconds, on a real failure | [n5](docs/evidence/n5-alert.txt) |
| N7 | Origin reachable only through CloudFront | Pass: direct S3 and function URL return 403 | `scripts/verify.py n7` |
| N8 | No long-lived AWS keys, including CI | Pass: GitHub Actions assumes a read-only role over OIDC, trusted only for this repository's immutable subject | [n8](docs/evidence/n8-oidc.txt) |

## Repository

| Path | What |
|---|---|
| `edge/` | CloudFront Functions and their tests |
| `api/` | The storefront API (Lambda) |
| `glue/` | The Spark job: parsing, pseudonymisation, quarantine, bot rules, data quality; tests run locally on Spark |
| `sql/` | Star schema and report tables, re-runnable per day |
| `pipeline/` | The Step Functions task function: runs SQL, reconciles, publishes the dashboard data |
| `terraform/` | All infrastructure, with a Checkov config where every skipped check has its reason |
| `traffic/` | Real traffic generator and synthetic log generator with planted answers |
| `scripts/` | Requirement checks (`verify.py`) and ground-truth comparison (`check_truth.py`) |

## Running it

```bash
cd terraform
terraform init -backend-config="bucket=<state bucket>" -backend-config="region=eu-west-2"
terraform apply
python ../traffic/real.py --base-url "$(terraform output -raw site_url)" --visitors 300 --workers 6
python ../traffic/synthetic.py --start 2026-10-10 --days 7 --bucket "$(terraform output -raw raw_bucket)"
aws stepfunctions start-execution --state-machine-arn "$(terraform output -raw state_machine_arn)" \
  --input '{"start":"2026-10-10","end":"2026-10-17"}'
python ../scripts/verify.py n3 && python ../scripts/check_truth.py ../docs/evidence/truth.json
terraform destroy
```

Tests: `node --test` in `edge/`; `pytest` in `api/`, `pipeline/` and `glue/` (Spark tests need Java 17).
