# Options and decisions

How each part of the design was chosen against the [brief](01-brief.md). Prices are for eu-west-2 (London) unless stated, taken on 16 October 2026 from the AWS Pricing API or the AWS pricing and documentation pages linked at the end. Usage figures are estimates and are marked as such; the measured bill is reported after teardown.

## Proposed architecture

```
Visitors ──► CloudFront ──► CloudFront Functions (A/B group, URL normalisation, security headers)
                 │   ├──► S3: static site            (private, Origin Access Control)
                 │   └──► Lambda function URL: API   (Origin Access Control)
                 │
                 └──► Standard logs (v2) ──► S3 raw     (7-day lifecycle, IPs present)
                                                 │
EventBridge Scheduler ─► Step Functions ─────────┤
                                                 ▼
                                   Glue Spark job: parse, pseudonymise IPs, classify bots,
                                   Glue Data Quality rules, quarantine bad rows
                                                 │
                                   S3 clean (Iceberg, no raw IPs) + S3 quarantine
                                                 │
                                   Athena SQL: star schema and report tables (Iceberg)
                                                 │
                                   Reconciliation check ─► SNS alert on failure
                                                 │
                                   Dashboard data ─► S3 site ─► CloudFront
Access to clean and curated tables: Lake Formation (column-level)
```

## Decisions

### D1. How logs get from CloudFront to the platform

| Option | Cost | Notes |
|---|---|---|
| Real-time logs to Kinesis Data Streams | $0.01 per million log lines, plus Kinesis | **Not available**: Kinesis returns `SubscriptionRequiredException` on this account. Also unnecessary: the brief needs daily data. |
| Standard logging (v2) to CloudWatch Logs | Vended-logs ingestion beyond 750 bytes per request | Logs would then need exporting to S3 for Spark and Athena. Extra hop. |
| **Standard logging (v2) to S3, W3C text, Hive-style partitions** | **No delivery charge**, only S3 storage | AWS: "There are no additional charges for log delivery to Amazon S3." Partitioned by date and hour, which the Glue job reads directly. Supports the extra fields this design needs: `c-country`, `asn`, `time-to-first-byte` and `viewer-request-log-data`. |
| Standard logging (v2) to S3 as Parquet | CloudWatch format-conversion charge | Saves one conversion step, but costs extra and the raw layer should stay as delivered. |
| Standard logging (legacy) to S3 | Free | Needs S3 ACLs enabled on the bucket, which AWS now recommends against. Fewer fields. |

**Decision:** v2 to S3 in W3C text. Tested on day one: configured through the CloudWatch API in us-east-1, delivered to a bucket in eu-west-2 within about a minute, with Hive-style partitions and every field requested.

### D2. Logic at the edge

| Option | Cost | Notes |
|---|---|---|
| **CloudFront Functions** | 2,000,000 invocations a month free | Runs on every request at every edge location in under a millisecond. Enough for A/B assignment, URL normalisation and headers. `cf.logCustomData()` writes the A/B group straight into the access log. |
| Lambda@Edge | $0.0000006 per request (Pricing API) plus duration | **Not supported** on the Free plan. Would allow network calls and larger code; nothing in the brief needs that. |

**Decision:** CloudFront Functions on viewer request (assign or read the A/B group cookie, normalise the URL so equivalent requests share a cache entry, log the group) and viewer response (set the cookie and security headers).

### D3. The API behind the site

| Option | Cost | Notes |
|---|---|---|
| **Lambda function URL behind CloudFront, protected with Origin Access Control** | Lambda free tier: 1,000,000 requests and 400,000 GB-seconds a month | No extra service. Only CloudFront can call it. |
| API Gateway HTTP API | Per-request charge (not priced here) | Adds throttling, routing and authorisers the API does not need. |

**Decision:** function URL with Origin Access Control. Tested on day one: through CloudFront the API returned 200; calling the function URL directly returned 403.

### D4. Processing the raw logs

| Option | Fit | Notes |
|---|---|---|
| **AWS Glue Spark job** | Good | Parses the W3C format, applies keyed hashing with a secret (D8), classifies user agents, applies data-quality rules and writes good and bad rows to separate places in one pass. $0.44 per DPU-hour, billed by the second. Estimated $1.60 to $3.50 for about 60 runs at 2 DPU for about 4 minutes (estimate). |
| Athena SQL directly over the raw text | Partial | Cheaper at this volume ($5 per TB scanned). But keyed hashing with a secret, quarantining bad rows and user-agent parsing are awkward in SQL, and the secret would have to appear in queries. |
| Lambda per log file | Partial | Fine for small files; no built-in data-quality rules; harder to re-process a whole day. |
| Amazon EMR Serverless | Not available | Amazon EMR is listed for the Paid plan only. |

**Decision:** one Glue Spark job, written and tested by the platform team. It is the only Python component; everything the client's team changes day to day (the model and reports) is SQL, in line with the constraint. At this volume Athena alone would be cheaper; Glue is chosen for the pseudonymisation and quarantine requirements (N1, N3). Volume alone would never justify it.

### D5. Data quality

| Option | Notes |
|---|---|
| **Glue Data Quality rules inside the job** | Rules are declarative (DQDL), so the client's team can read them. No separate charge: AWS says rules in ETL jobs result in "increased runtime or increased DPU consumption", and anomaly detection in ETL jobs has "no additional charge". |
| Great Expectations | Python framework; conflicts with the team constraint. |
| Hand-written checks | No standard format; harder to review. |

**Decision:** Glue Data Quality. Rows that cannot be parsed (wrong field count, unparseable timestamp, status or bytes, missing request id, malformed edge location) go to a quarantine table with the reason. Dataset-level rules (complete and unique request ids, valid status codes and classes, no unmasked IP address in any output column) fail the run, and so does a row count that does not reconcile (raw = clean + quarantined, N3).

**Changed during the build:** an edge code that is well formed but missing from the edge location seed is no longer quarantined. CloudFront adds edge locations faster than any seed file is updated, and a valid request should not be discarded because of a reference table. Such rows are kept and reported as `Unknown` location and pricing region, so a growing `Unknown` share is the signal to refresh the seed.

### D6. Orchestration

| Option | Cost | Notes |
|---|---|---|
| **Step Functions, started by EventBridge Scheduler** | $0.000025 per state transition; first 14 million scheduled invocations free | Native steps for Glue jobs and Athena queries that wait for completion. Retries, timeouts and failure branches in the definition. Every run is visible as a diagram. |
| Amazon MWAA (managed Airflow) | $0.33 an hour for the smallest environment, about $244 a month | Would use the whole $10 budget in about 30 hours. The team does not know Airflow. |
| Self-hosted Airflow | A server, always on | The team will not run servers. |
| Glue workflows | Glue pricing | Orchestrates Glue jobs and crawlers only; Athena steps and alerting would need workarounds. |

**Decision:** Step Functions with EventBridge Scheduler.

**Account limit found during the build:** this account's Lambda concurrency quota is 10, and AWS requires 10 to stay unreserved, so no function can have reserved concurrency. The state machine processes one day at a time (Map, `MaxConcurrency` 1), which also keeps Glue to one run at once. A production account would raise the quota and reserve concurrency for the pipeline function.

### D7. Data model and storage format

| Option | Notes |
|---|---|
| **Apache Iceberg tables in the Glue Data Catalog, queried and built with Athena SQL** | Iceberg supports `DELETE` and `MERGE`, so re-processing a day replaces it cleanly (N4). Athena costs $5 per TB scanned; partitioned Parquet keeps scans small. |
| Plain Parquet with Hive partitions | Re-processing a day means deleting S3 prefixes outside SQL. |
| Amazon Redshift Serverless | Listed for the Paid plan only; minimum capacity charges while running. |
| dbt | Excluded: another tool for a four-person team, and the models are few enough for plain SQL. |

**Decision:** Iceberg tables. A star schema: `fact_request` at one row per request, with `dim_date`, `dim_edge_location` (code, city, country, CloudFront price-class region), `dim_content` (path group, content type) and `dim_client` (device class, bot class). Report tables are built from it with Athena SQL run by Step Functions.

### D8. Personal data (IP addresses)

The ICO treats pseudonymised data as personal data, so hashing alone is not enough; it must be combined with access control (D9).

| Treatment | Used for |
|---|---|
| Truncate to /24 (IPv4) or /48 (IPv6) | Network-level analysis and bot heuristics |
| HMAC-SHA256 with a secret key, rotated monthly | Counting unique visitors; not reversible without the key |
| Drop the full address | Everywhere after the raw layer |
| Country | Taken from CloudFront's own `c-country` field, so no IP geolocation database is needed |

The HMAC key is held in AWS Systems Manager Parameter Store as a standard SecureString parameter encrypted with the project KMS key. Standard parameters have no storage or API charge; the Pricing API lists charges only for advanced parameters ($0.05 a month) and higher throughput. Raw logs expire after 7 days (S3 lifecycle).

### D9. Access control

| Option | Notes |
|---|---|
| **Lake Formation** | Column-level grants on Glue tables: the analyst role cannot select the pseudonymised visitor column. Lake Formation is on the Free plan's supported list. |
| IAM and S3 prefix policies only | Cannot restrict individual columns. |

**Decision:** Lake Formation, with two roles tested: `analyst` (aggregates and dimensions only) and `data-engineer` (everything except the raw bucket, which only the Glue job reads).

### D10. Encryption

**Decision:** one customer-managed KMS key ($1 a month) for the raw, clean, quarantine and curated buckets and the Parameter Store key. The key policy allows the CloudWatch log delivery service to write to the raw bucket, which AWS documents for KMS-encrypted log buckets. The static site bucket uses S3-managed encryption: its content is public through CloudFront anyway.

### D11. Dashboard

| Option | Notes |
|---|---|
| **Static page built from Athena results, served through the same CloudFront distribution** | No extra service; shows the edge platform delivering its own analytics. |
| Amazon Quick (QuickSight) | On the supported list in its Free and Plus editions; adds a service and licensing questions for viewers. |
| Amazon Managed Grafana | Not available on the Free plan. |

**Decision:** static page.

**Changed during the build:** the page is now a small React app with charts from the Bklit UI registry, built with Vite. It is still static: Terraform uploads the build to `insights/`, and the page reads the `data.json` the pipeline publishes next to it.

### D12. Bot classification

**Decision:** rules in the Glue job: known crawler user agents, missing or scripted user agents, request rate per truncated network, and absence of page assets. Recorded as `human`, `known_bot` or `suspected_bot`. AWS WAF Bot Control is the production recommendation and is out of scope.

## Estimated build cost

| Service | Basis | Estimate |
|---|---|---|
| CloudFront and CloudFront Functions | Under the monthly free allowance | $0 |
| Lambda, EventBridge Scheduler, Glue Data Catalog | Under free allowances | $0 |
| Glue Spark | About 60 runs. A test job used 168 DPU-seconds, about $0.02 at $0.44 per DPU-hour; real runs will be longer | $1.20 to $3.50 |
| Athena | A few hundred queries over partitioned Parquet | Under $1 |
| S3 | A few GB for a few weeks | Under $0.30 |
| KMS | One key | Up to $1 |
| Step Functions, CloudWatch | About 1,500 transitions; 3 alarms | Under $0.60 |
| **Total** | | **About $3 to $7 (estimate)** against $179.95 of credit |

Things that would cost more if left running, and the control for each: Glue interactive sessions (not used), anything billed hourly (nothing in this design), forgotten resources (`terraform destroy` plus a check that nothing is left, and a $10 budget alarm).

## Day-one checks (17 October 2026)

Run with the AWS CLI on throwaway resources tagged `edge-spike`, then deleted. A final check found nothing left by tag or by name in either Region.

| Check | Result |
|---|---|
| Standard logging (v2) from CloudFront to a bucket in eu-west-2 | **Pass.** Delivered within about a minute, partitioned `distributionid=/year=/month=/day=/hour=`, with `c-country`, `asn`, `time-to-first-byte` and `viewer-request-log-data` present |
| Origin Access Control for S3 and for a Lambda function URL | **Pass.** Through CloudFront: site 200, API 200. Direct to S3: 403. Direct to the function URL: 403 |
| Parameter Store standard parameters | **No charge** (Pricing API lists charges for advanced parameters only) |
| Glue Spark job (Glue 5.0, 2 workers) | **Pass.** 84 seconds, 168 DPU-seconds, about $0.02 |
| Athena with Iceberg: create, insert, delete a day, re-insert, query | **Pass.** The re-processed day totalled 27 rows. A duplicate would have made 52 |

Requests from the developer's laptop were served by the Tel Aviv edge location (`TLV55`) on this day. On build day the same laptop was served from Johannesburg (`JNB51`) and Lagos (`LOS`), so test traffic is always described by the edge location recorded in the log, never by assumption.

## Sources

- [CloudFront standard logging (v2), including pricing note](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/standard-logging.html)
- [CloudFront pricing and free tier](https://aws.amazon.com/cloudfront/pricing/)
- [AWS Glue pricing, including Data Quality](https://aws.amazon.com/glue/pricing/)
- [AWS Lambda pricing](https://aws.amazon.com/lambda/pricing/)
- [Services supported on the AWS Free plan](https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html)
- AWS Pricing API (`aws pricing get-products`) for Glue, Athena, CloudFront, S3, KMS, Step Functions, EventBridge, Lambda, CloudWatch and MWAA in eu-west-2
