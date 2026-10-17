# Build log

Everything that went wrong while building this, in the order it happened, and what I did about it. All of it happened on this build. Some of it was AWS, some of it was my own code, and a few were the tests themselves.

## Before building

### The Free plan ruled out streaming and Lambda@Edge

Kinesis Data Streams and Firehose both returned `SubscriptionRequiredException`, and Lambda@Edge isn't available on the plan at all. So real-time logs were off the table. I switched to CloudFront standard logging (v2) into S3, processed once a day, which still meets the 06:00 deadline in the brief. All the edge logic became CloudFront Functions.

I found this on day one because I tried the services before designing around them. Finding it after the design was settled would have been far more expensive.

### Lambda concurrency is capped at 10

I couldn't set reserved concurrency on any function. This account's Lambda quota is 10, and AWS insists that 10 stay unreserved, so there's nothing left to reserve. New accounts get lower quotas than the documentation suggests.

The Step Functions Map processes one day at a time, and the traffic generators run 6 workers so the API stays under the limit. Checkov's reserved-concurrency check is skipped with this reason written next to it.

### The two edge functions can't share anything

The viewer-response function can't see a header that the viewer-request function added. CloudFront Functions keep no state between the two events. To keep a visitor in the same A/B group, both functions compute the group from the same input, an FNV-1a hash of the IP and user agent, and so both get the same answer without talking to each other.

## Day-one spike

Three small ones. The AWS CLI rejected the log delivery `suffixPath` setting in shorthand syntax, so I passed it as JSON. Terraform state lost track of the S3 Origin Access Control partway through; I took its ID from the distribution and brought it back under management before tearing the spike down. And the pricing script crashed with a `KeyError` because some entries in the AWS Price List API aren't priced in USD. It skips those now.

## Main build

### The test data generator pulled in Spark

The synthetic log generator should only need the standard library, but it wouldn't import without PySpark. It took the field list from the Glue transform module, which imports Spark at the top. The 33 field names now live in their own module, `glue/edge_etl/fields.py`, and both use it.

### Three bugs in the Glue job

Rows were landing on the wrong day, a re-run left the previous run's quarantined rows behind, and the exit handling misreported failures. All three are fixed in `glue/process_logs.py`. A re-run now replaces the whole day in the clean table and clears the day in the quarantine table first (N4).

### Smaller fixes

The Lake Formation grant that hides `visitor_id` from analysts was rejected until I added `wildcard = true` next to `excluded_column_names`. The `Project` cost tag didn't show in Cost Explorer because cost allocation tags have to be activated in Billing first. I activated it so the build's cost can be measured on its own (N10).

### The security scan

Checkov flagged a range of things across the Terraform. Some were real gaps and I fixed them: KMS encryption on the log groups and the alert topic, a Glue security configuration, tracing on the pipeline function. The rest are skipped in `terraform/.checkov.yml`, each with the reason beside it. WAF, for example, costs at least $5 a month per web ACL, which doesn't fit a $10 budget. Five failures were false positives: the bucket module does have the abort-multipart lifecycle rule, and Checkov can't see it through the module.

Then I noticed the CI job pointed at the config file from the wrong folder. CI would have ignored every skip and failed. Fixed.

## Deploying

### First deploy: a placeholder inside a comment

The step that creates the curated tables at deploy time failed with `Invalid placeholder in string`. The SQL files use `${name}` placeholders, and a comment explaining them contained the text `${...}`. My renderer filled placeholders before stripping comments. It strips comments first now, and I render all three SQL files locally before deploying.

### Second deploy: IAM hadn't reached Athena yet

`Access to the specified S3 resource is denied` on the first Iceberg table, even after I gave the pipeline role write access to the curated folder. The bucket policy and the KMS key policy were both fine. CloudTrail showed no Lake Formation credential request and no KMS denial, so Athena was using the role's own credentials, as expected. I ran the same step by hand a minute later and all 22 statements went through.

IAM changes take a few seconds to spread, and Terraform ran the step the moment the policy was attached. There's now a 20-second `time_sleep` between the two. Retrying first was the right call here: rewriting the policy would have changed nothing.

### A Terraform diff that wouldn't go away

Every plan wanted to replace the three Lake Formation database grants, because AWS reported `ALL` for a role I'd only given `DESCRIBE`. Listing every grant on the database showed the analyst with `DESCRIBE` only. Listing the analyst's grants on the same database returned `ALL, DESCRIBE`. AWS folds the database's `IAM_ALLOWED_PRINCIPALS` grant into each role's answer.

That grant was the real problem. It's the account default for new databases, and it meant any role with Glue IAM permissions could create tables in the curated database without going through Lake Formation at all. I revoke it for this one database inside Terraform. The account default stays as it is, so other projects in the account don't notice. The pipeline still builds every table and the plan is clean.

My first version of the revoke command had a shell precedence bug, `a || b && exit 1`, which exits even when `a` succeeds. It's rewritten to succeed whether the grant is removed now or was already gone.

I could have hidden the diff with `ignore_changes`. I'm glad I didn't.

### Missing pages came back as 403

A request for a page that doesn't exist returned 403 through CloudFront. S3 answers a missing object with 403 if the caller can't list the bucket. That would have hidden every broken link from the error report (F6). CloudFront, and only this distribution, can now list the site bucket, so a missing page is a real 404. Going to the bucket directly still gets 403 (N7).

### Spark tests on a laptop

First there was no Java. Then `PYTHON_VERSION_MISMATCH`, because Spark's workers picked up the system Python 3.15 while the driver ran 3.11. Then one timestamp came back two hours out: `collect()` converts timestamps to the machine's local time zone, even with the Spark session set to UTC. I installed Java 17 to match CI, and the test setup now pins the workers to the test's own Python and runs in UTC, as Glue does. 12 of 12 passed.

## Running it

### Real traffic came through a different edge location

On the day-one checks my laptop was served from Tel Aviv (TLV55). On build day the same laptop went through Johannesburg (JNB51), with a few requests through Lagos. GitHub's US runners went through Chicago (ORD). CloudFront picks the edge location with the best latency at that moment, and that moves. The reports only ever use the edge location written in each log line.

### The first backfill was stopped by its own privacy check

The first backfill failed on its first day. A data quality rule meant to catch IP addresses in the user agent found plenty, and every one was a browser version: `Chrome/131.0.0.0` looks exactly like an IPv4 address. My rule was wrong.

The check now asks the question I actually meant. While the raw address is still known, each row is flagged if any text column that gets kept (user agent, path, referrer, query parameter names) contains that request's own IP, and the rule needs zero flagged rows. A test covers both cases.

The failure itself went the way it should. Nothing was written, Step Functions caught the error, and the alarm reached the alerts queue 70 seconds after the run stopped. N5 allows 15 minutes.

### Shared query results would have undone the column restriction

I found this while writing the N2 test. The analyst and data engineer roles shared one Athena workgroup and one results folder. Lake Formation stops an analyst selecting `visitor_id`, but Athena writes every query's results to S3, so an analyst could simply have opened the results file of an engineer's query.

Each role now has its own workgroup and results prefix and can use only those. Both roles also lost catalog access to the clean layer, which they never needed. The N2 test checks that the analyst can't open the engineer's results.

### IPv6 addresses in rejected lines

Also found while writing a test. Rejected log lines are kept for diagnosis with addresses masked, and the mask only matched IPv4. A malformed line from an IPv6 visitor would have kept the full address. The line's own client address is now replaced first, then anything shaped like an IPv4 or IPv6 address. The IPv6 pattern needs `::` or all eight groups, so log times such as `21:59:16` are left alone. My synthetic data produces both address families, and the tests cover both.

No line was quarantined during the build, so nothing leaked before the fix.

### The privacy scan flagged a coincidence

The first N1 scan reported raw client addresses in `client_network`. All 29,431 distinct values were proper /24 or /48 networks. 330 of them happened to equal a raw address because the generator sometimes produced a host address ending in `.0`, and that's identical to its own network. It reveals nothing beyond the network.

For that one column the test now checks that every value is a network address. Every other text column is still compared against the real raw addresses. The scan also had a `LIMIT 5000` that could have dropped matches without saying so. Gone.

### Two planted answers missed on the first comparison

The first truth check got requests, bots, broken links, the incident and the experiment effect right. It failed on bytes by country (up to 2.1% high, all in the US) and on visitor counts (one visitor short, one day, one group). Both problems were in my comparison.

The generator's `bytes_by_country` counts human visitors only. Known crawlers are generated in the US, so the platform's all-traffic figure was correctly higher. Against the platform's human-only bytes, every day and country matches exactly.

A visitor is an IP and user agent pair, on the site and in the platform. Synthetic IPv4 addresses come from a pool of about four million, so now and then two generated sessions draw the same pair and become one visitor to any system. The generator now records distinct visitors too. That change uses no randomness, and I checked it: all 168 regenerated log files are byte-identical, once decompressed, to the ones processed, and no existing truth value moved. The platform matches the distinct counts exactly. There was one shared pair all week.

I didn't loosen any tolerance. Both explanations were proven before the test changed.

### Re-running a day changed two tables, then one

N4 says a day can be processed again with identical results, so the test takes a row count and checksum of every table, re-runs the day, and compares. The first attempt couldn't read the request table at all (an array column won't cast to text). I stopped the re-run before Glue started, fixed the snapshot and started again.

Then 9 of 11 tables matched, including the 184,389-row request table. The two that didn't hold response-time percentiles from Athena's `approx_percentile`, which can return slightly different values on each run. They're exact now: sort the values and take the one at position ceil(p × n). With at most about 185,000 values per group it costs next to nothing.

The next attempt matched 10 of 11. The cost table's checksum had flipped back to an earlier value. It added up decimal GB figures from another report table, and decimal addition can round differently depending on the order. It now totals whole bytes per pricing region from the request table and multiplies by the price once. Because a fault like that only shows some of the time, I re-ran two days, 12 and 13 October. Both matched on every table.

## Publishing

### CI ran a newer scanner than my laptop

Checkov passed locally with 186 checks and failed on the first push with 248 checks and 23 failures. CI pulls the latest image (3.3.29) and my laptop had 3.3.20. I went through each new finding. Two conflict with the brief. Cross-region replication would move data out of eu-west-2, which N6 forbids. Versioning on the raw bucket would keep deleted logs, IP addresses included, past the 7 days N1 allows. Every skip has its reason in the config. With the local scanner on the same version, it's 248 passed and 0 failed.

### CI couldn't assume its role

The first OIDC run failed with `Not authorized to perform sts:AssumeRoleWithWebIdentity`, even though the trust policy named the repository correctly. GitHub now issues this repository's tokens with an immutable subject that includes the owner and repository IDs (`repo:owner@id/name@id:...`). The trust policy matches that form now, and it's stricter: a repository deleted and re-created under the same name can't assume the role. The role ARN moved into a repository secret so the account ID doesn't show on public run pages.

`gh api repos/OWNER/NAME/actions/oidc/customization/sub` shows what a repository's tokens will actually say. I'd check it first next time.
