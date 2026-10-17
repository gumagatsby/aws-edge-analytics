# Brief: edge analytics for a global online retailer

*A portfolio scenario. The client is fictional; the AWS services, prices, constraints and measurements are real.*

## Background

The client is a UK online retailer that sells to customers worldwide. Its storefront is a static site with a small API, served through Amazon CloudFront. The engineering team is four people. They know SQL well, have little Python, and do not want to run servers.

CloudFront logs every request, but nobody reads the logs. Five problems have reached the architect:

| # | Problem | Raised by |
|---|---|---|
| P1 | The CDN bill keeps rising, and nobody can say which regions or content drive it. | Finance |
| P2 | Customers in some countries say the site is slow. Nobody knows if the cause is the cache, the origin or the distance. | Customer service |
| P3 | Marketing redesigned the homepage and wants to know whether it worked. There is no experiment framework. | Marketing |
| P4 | Traffic figures look inflated. Nobody knows how much is bots. | Leadership |
| P5 | The logs contain visitor IP addresses, which are personal data under UK GDPR, and are kept indefinitely. | Legal |

## Objective

Build a platform that answers P1 to P4 from CloudFront's own logs, fixes P5, and ends with recommendations the client can act on.

## Requirements

### Functional

| ID | The platform must | Answers |
|---|---|---|
| F1 | Report requests, bytes and cache hit ratio by edge location, country, content type and day | P1, P2 |
| F2 | Report response time (total and time to first byte) by edge location and country, split by cache hit and miss | P2 |
| F3 | Estimate CDN cost by region from the logs, and model the saving from a cheaper CloudFront price class | P1 |
| F4 | Assign each visitor to an A/B group at the edge, keep them in it, and report the results per group | P3 |
| F5 | Classify requests as human, known bot or suspected bot, and report the share | P4 |
| F6 | Report error rates (4xx, 5xx) by path and edge location | P2 |
| F7 | Publish the results on a dashboard served through the same CloudFront distribution | All |

### Non-functional

| ID | Requirement | How it is checked |
|---|---|---|
| N1 | **No raw IP address** is stored beyond the raw log layer. Raw logs are deleted after 7 days. | A test scans every curated table for IPv4 and IPv6 patterns; S3 lifecycle rule in Terraform |
| N2 | Analysts can see aggregated data only. Pseudonymised visitor identifiers are visible only to the data engineering role. | Lake Formation column permissions, tested with both roles |
| N3 | **Every row is accounted for**: raw rows = clean rows + quarantined rows, for every run. | Reconciliation step in every run; the run fails if it does not balance |
| N4 | Any day can be re-processed without creating duplicates. | Run the same day twice; results must be identical |
| N5 | Data is ready by 06:00 UTC for the previous day. A failed run alerts within 15 minutes. | Scheduled run; alarm on failure |
| N6 | Data stays in the UK region (eu-west-2) once it lands. | All buckets, Glue and Athena in eu-west-2 |
| N7 | All storage is private and encrypted. The origin can be reached only through CloudFront. | Bucket policies, Origin Access Control; direct-origin request test must fail |
| N8 | No long-lived AWS keys anywhere, including CI. | GitHub Actions uses OIDC |
| N9 | Everything is defined in Terraform and can be destroyed completely. | `terraform destroy`, then a check that nothing is left |
| N10 | Build cost under **$10**, measured from the AWS bill. | Budget alarm at $10; Cost Explorer after teardown |

### Constraints

| Constraint | Effect on the design |
|---|---|
| The AWS account is on the Free plan. Kinesis and Firehose return `SubscriptionRequiredException`; Lambda@Edge is not supported. | No real-time log streaming; no Lambda@Edge. Edge logic must use CloudFront Functions. |
| The team knows SQL, not Python frameworks, and will not run servers. | Transformations the team maintains are SQL. No self-hosted orchestrator. |
| Budget under $10 for the build. | Nothing billed by the hour while idle. |

## Scope

**In:** CloudFront distribution and edge functions, a static site and a small API, log collection, processing, data quality, data model, orchestration, alerting, access control, dashboard, recommendations, Terraform, CI/CD.

**Out:** payment processing, a real product catalogue, a production-grade bot management service (AWS WAF Bot Control is noted as the production option), real-time dashboards.

## Traffic used for testing

The site gets no real customers, so traffic is generated two ways, and every report says which is which:

1. **Real CloudFront traffic** from two places: a load generator on the developer's laptop (served from whichever edge location CloudFront chooses: Tel Aviv on the day-one checks, Johannesburg and Lagos on build day), and GitHub Actions runners in the United States. These produce genuine CloudFront logs from real edge locations, and the parser is tested against them.
2. **Synthetic logs** in CloudFront's exact format, simulating a worldwide audience, a homepage experiment with a known built-in effect, and a known share of bots. Because the true answers are known, the synthetic data tests whether the platform finds them.

## Success criteria

1. Each of F1 to F7 is answered with figures from the platform.
2. On the synthetic data, the platform recovers the planted bot share and experiment effect within stated tolerances.
3. N1 to N10 are each demonstrated, with evidence in the results document.
4. A recommendation on the price class, cache settings and the homepage, each with its expected effect.
5. The real AWS bill for the build, reported after teardown.
