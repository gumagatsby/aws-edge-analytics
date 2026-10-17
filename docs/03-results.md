# Results

What the platform found, whether it met the brief, and what the client should do next. Every figure comes from the platform's own tables or from a check script, and each one links to its evidence. The dashboard published by the pipeline shows the same figures: `/insights/` on the site distribution while the stack was deployed.

Two kinds of traffic were processed, and each figure says which it comes from.

| | Real traffic | Synthetic week |
|---|---|---|
| What it is | Genuine CloudFront logs from a load generator on a laptop and from GitHub's US runners | Logs in CloudFront's exact format with known answers planted in them |
| Volume | 11,722 requests on 17 October 2026 | 1,295,525 requests, 10 to 16 October 2026 |
| Edge locations | Johannesburg, Lagos, Chicago | 38 worldwide |
| Good for | Proving the parser and edge functions on real logs | Proving the reports find the right answers |

Rates from the real traffic move a lot because the volume is small, and the countries in it say where the test machines were, not where customers are.

## The questions from the brief

### P1. What the CDN costs, and whether a cheaper price class is worth it

Cost is estimated from the bytes in each log line, priced by the region of the edge location that served it, at list price from the AWS Pricing API (first 10 TB a month). The free tier is not deducted, so these are what the traffic would cost a paying customer.

On the synthetic week, 114.4 GB cost $10.74. Europe is the largest share at $4.55, then the United States at $1.77. Every other region is under $0.80.

| If the distribution used | Cost for the week | Saving | Served from a further edge location |
|---|---|---|---|
| All edge locations (current) | $10.74 | | |
| Price class 200 | $10.37 | 3.4% | 13.5 GB (12%) |
| Price class 100 | $9.73 | 9.4% | 36.5 GB (32%) |

Price class 100 saves about $1 on this week's traffic, and it does it by sending a third of the bytes to visitors in Australia, South America, India and Asia from edge locations further away. Those are the regions that already have the slowest cache misses (P2).

### P2. Where the site is slow, and why

Time to first byte, median, by edge location. Synthetic week:

| Edge location | Cache hit | Cache miss |
|---|---|---|
| London, Manchester | 10 ms | 38 ms |
| Auckland | 10 ms | 325 ms |
| Melbourne | 10 ms | 306 ms |
| Sydney | 10 ms | 305 ms |
| Seoul | 10 ms | 270 ms |

A cache hit takes about 10 ms everywhere. A miss goes back to the origin in London, so its time grows with the distance from London. The slowness customers report comes from cache misses far from the UK, not from slow edge locations.

The real traffic shows the same pattern on genuine CloudFront timings: misses took a median of 330 ms in Lagos, 195 ms in Johannesburg and 104 ms in Chicago, while hits took 2 to 3 ms. Lagos served only 33 requests, with a hit ratio of 7.1%, so it missed nearly every time.

Errors are part of P2 too. All 3,180 client errors in the synthetic week were 404s, one broken product link (`/products/13.html`) requested from many places. All 245 server errors were 502s from the API at the Singapore edge location on 13 October: the planted incident, found exactly.

### P3. Whether the homepage redesign worked

Visitors are assigned to design A or B at the edge and kept there by a cookie. Only people are counted, not bots. Synthetic week:

| Design | Visitors | Bought | Conversion |
|---|---|---|---|
| A (current) | 42,227 | 1,220 | 2.89% |
| B (redesign) | 41,772 | 1,471 | 3.52% |

B converts 0.63 percentage points better, with a 95% interval of 0.39 to 0.87 points (two-sided z-test, p < 0.001). The planted lift was 0.60 points, inside the interval.

On the real traffic, the test reports "too few visitors to tell yet": 114 visitors, and an interval from 6 points worse to 13 points better. That's the right answer for that volume.

### P4. How much of the traffic is bots

Synthetic week: 12.0% of requests were bots. Known crawlers were 7.4%, scripted or missing user agents 4.6%, and pages fetched without their stylesheets or images 0.04%. The planted share was found to within 0.005 percentage points on every day ([evidence](evidence/truth-recovery.txt)), including a scraper posing as a browser.

Real traffic: 16.7%. The load generator sends crawler and scraper sessions on purpose. A further 8.6% was flagged by request rate. Assessment (unverified): these are most likely the generator's simulated shoppers, which all come from one laptop address and so look like one very busy network.

### P5. Visitors' IP addresses

Fixed. Raw logs are deleted after 7 days. After the raw layer, no full address is kept anywhere: networks are truncated to /24 or /48, and visitors are counted with a keyed hash whose key analysts can't reach. N1 and N2 below are the proof.

### Cache key normalisation

Homepage links from campaigns arrive with tracking parameters (`utm_source`, `gclid`), and CloudFront treated each combination as a different page. The viewer-request function strips them before the cache lookup.

| Homepage requests with tracking parameters | Hit ratio, normalisation off | Hit ratio, normalisation on |
|---|---|---|
| Real traffic, the same 3,933 requests replayed | 1 of 99 (1.0%) | 99 of 99 (100%) |
| Synthetic week | 8.0% | 97.5% |

## Requirements

| | Requirement | Result | Evidence |
|---|---|---|---|
| F1 | Requests, bytes and hit ratio by edge, country, content and day | Met | Dashboard, `agg_edge_daily`, `agg_country_daily` |
| F2 | Response time by edge and country, hit and miss | Met | P2 above |
| F3 | Cost by region and the price class model | Met | P1 above |
| F4 | A/B assignment at the edge, sticky, reported per group | Met | P3 above; edge function tests |
| F5 | Human, known bot and suspected bot | Met | P4 above |
| F6 | Errors by path and edge | Met | P2 above |
| F7 | Dashboard on the same distribution | Met | `/insights/`, deployed by Terraform |
| N1 | No raw IP beyond the raw layer; raw logs deleted after 7 days | Pass: 85 text columns compared against 96,661 real raw addresses | [n1](evidence/n1-no-raw-ip.txt) |
| N2 | Analysts see aggregates only | Pass, 8 checks | [n2](evidence/n2-access.txt) |
| N3 | Raw = clean + quarantined, every run | Pass, every day and source | [n3](evidence/n3-reconciliation.txt) |
| N4 | Re-processing a day gives identical results | Pass: 11 tables, two days re-run | [n4](evidence/n4-rerun.txt) |
| N5 | Alert within 15 minutes of a failure | Pass: 70 seconds, on a real failure | [n5](evidence/n5-alert.txt) |
| N6 | Data stays in eu-west-2 | Pass: every bucket in eu-west-2 | [n6](evidence/n6-region.txt) |
| N7 | Origin reachable only through CloudFront | Pass: direct S3 and function URL return 403 | `scripts/verify.py n7` |
| N8 | No long-lived AWS keys, including CI | Pass: OIDC, immutable subject | [n8](evidence/n8-oidc.txt) |
| N9 | Everything in Terraform, destroyed completely | Pass: 144 resources destroyed, nothing left but the KMS key in its 7-day deletion window | [n9](evidence/n9-teardown.txt) |
| N10 | Build under $10 on the AWS bill | Recorded after teardown | |

## Recommendations

### Ship design B

It converts 0.63 points better, a relative lift of about 22%, and the whole interval is above zero. Keep the edge assignment running after launch with a small holdout on A, so the lift can be measured on real customers rather than assumed.

### Keep all edge locations

Price class 100 would save 9.4% of the CDN bill, about $1 a week at this volume. It would move a third of the traffic, all of it outside Europe and North America, to edge locations further from the visitor. The slowest of those visitors already wait 260 to 325 ms on a cache miss. Revisit if traffic from those regions falls, or if the bill grows enough that 9.4% matters more than their speed.

### Keep the cache key normalisation on, and fix the cache misses far from London

The normalisation took campaign traffic from 8% to 97.5% hits, at no cost. For far regions, the remaining problem is the round trip to London on a miss. The hit ratio follows how busy each edge location is: 97.7% in London and Manchester, 90.5% in Auckland, and 91% to 92% at the other quiet locations. Each edge location keeps its own cache, and with a one-hour lifetime a page requested rarely in one place has often expired before its next request. Longer cache lifetimes on product pages would cut those misses. That wasn't measured here, so the next step is a trial with this dashboard as the before and after.

### Fix `/products/13.html`

Every client error in the week came from this one link.

### Plan for bot management in production

About one request in eight is a bot. The rules here are enough to report on bots, not to stop them. AWS WAF Bot Control is the production option. It was out of scope because any WAF web ACL costs at least $5 a month before Bot Control's own charges, against a $10 build budget.

## Cost of the build

Recorded after teardown, from Cost Explorer filtered by the activated `Project` tag.
