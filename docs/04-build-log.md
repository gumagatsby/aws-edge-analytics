# Build log: problems met and how they were solved

Kept during the build, for the walkthrough. Each entry is what was seen, why it happened, what was changed, and what it teaches. Nothing here is hypothetical: every entry happened on this build.

## Platform limits found before building

### Free plan rules out streaming and Lambda@Edge
- **Seen:** Kinesis Data Streams and Firehose calls returned `SubscriptionRequiredException`; Lambda@Edge is not supported on the plan.
- **Why:** the account is on the AWS Free plan.
- **Changed:** real-time logs dropped in favour of CloudFront standard logging (v2) to S3, processed daily. All edge logic written as CloudFront Functions.
- **Lesson:** check account-level service availability on day one, before the design depends on a service.

### Lambda concurrency limit of 10
- **Seen:** reserved concurrency could not be set on any function.
- **Why:** this account's Lambda concurrency quota is 10, and AWS requires 10 to stay unreserved, so nothing can be reserved.
- **Changed:** no reserved concurrency; the Step Functions Map runs one day at a time (MaxConcurrency 1); the local traffic generator is limited to 6 workers. Checkov's reserved-concurrency check (CKV_AWS_115) is skipped with this reason recorded.
- **Lesson:** new accounts have lower quotas than the documentation defaults. Read Service Quotas, not the docs page.

### Edge functions cannot pass data from request to response
- **Seen:** the viewer-response function could not read a header added by the viewer-request function.
- **Why:** CloudFront Functions do not share state between the two events.
- **Changed:** the A/B group is a deterministic hash (FNV-1a of IP and user agent), computed the same way in both functions, so both reach the same answer independently.
- **Lesson:** when two stateless components need to agree, make them compute the same deterministic result rather than pass messages.

## Day-one checks (spike)

### CLI shorthand rejected the log delivery path setting
- **Seen:** creating the log delivery configuration failed when `suffixPath` was passed in CLI shorthand.
- **Changed:** passed the setting as JSON.

### Terraform state lost track of an Origin Access Control
- **Seen:** during the spike, state no longer held the S3 Origin Access Control.
- **Changed:** recovered its ID from the CloudFront distribution and brought it back under management, then tore the spike down cleanly.
- **Lesson:** the deployed resource is the source of truth; state can be rebuilt from it.

### Price list contained non-USD entries
- **Seen:** the pricing script failed with a `KeyError` on some CloudFront price entries.
- **Why:** not every entry in the AWS Price List API is priced in USD.
- **Changed:** non-USD entries are skipped.

## Main build

### Test data generator pulled in Spark
- **Seen:** the synthetic log generator, which should need only the standard library, failed to import without PySpark.
- **Why:** it imported the field list from the Glue transform module, which imports PySpark.
- **Changed:** the 33-field list moved to its own module (`glue/edge_etl/fields.py`), shared by both.

### Glue job: day assignment, quarantine re-runs and exit handling
- **Seen:** rows were assigned to the wrong day, a re-run left stale quarantine rows, and the job's exit handling misreported failures.
- **Changed:** all three fixed in `glue/process_logs.py`; a re-run now overwrites the day's partitions in both the clean and quarantine tables (N4).

### Lake Formation column filter needed a wildcard
- **Seen:** the analyst grant that excludes `visitor_id` was rejected.
- **Changed:** `table_with_columns` needs `wildcard = true` alongside `excluded_column_names`.

### Cost tag not active
- **Seen:** the `Project` tag did not appear in Cost Explorer.
- **Why:** cost allocation tags must be activated in Billing before they are reported.
- **Changed:** activated it, so the build's cost can be measured on its own (N10).

### Security scan: every finding fixed or justified
- **Seen:** Checkov reported failures across the Terraform.
- **Changed:** real gaps fixed (KMS encryption on logs and the alert topic, a Glue security configuration, tracing on the pipeline). The rest are skipped in `terraform/.checkov.yml`, each with its reason (for example WAF, which is outside the budget). Five remaining failures were false positives: the bucket module has the abort-multipart lifecycle rule, but Checkov cannot see it through the module. Result: 182 passed, 0 failed.
- **Also found:** the CI step pointed at the config file relative to the wrong folder, so CI would have ignored every skip. Fixed to `terraform/.checkov.yml`.
- **Lesson:** a skip list is only honest if every skip has a written reason.

### First deploy failed: a placeholder inside a comment
- **Seen:** the deploy-time step that creates the curated tables failed with `Invalid placeholder in string`.
- **Why:** the SQL files use `${name}` placeholders, and a comment explaining them contained `${...}`. The renderer substituted before removing comments.
- **Changed:** comments are removed first, then placeholders are filled. All three SQL files are now rendered in a local check before deploying.

### Second deploy failed: IAM not yet visible to Athena
- **Seen:** `Access to the specified S3 resource is denied` on the first Iceberg table, even after S3 write access was added to the pipeline role.
- **Diagnosis:** the bucket policy and KMS key policy were correct. CloudTrail showed no Lake Formation credential request and no KMS denial, so Athena was using the role's own credentials. Invoking the same step by hand a minute later succeeded: all 22 statements ran.
- **Why:** IAM changes take a few seconds to reach other services, and Terraform invoked the step immediately after attaching the policy.
- **Changed:** a 20-second wait (`time_sleep`) between the policy and the step, so a fresh deploy does not race.
- **Lesson:** "access denied" straight after a policy change is often propagation, not a wrong policy. Prove it by retrying before rewriting the policy.

### Permanent Terraform diff on Lake Formation grants, and a governance gap behind it
- **Seen:** every plan wanted to replace the three database grants, because AWS reported `ALL` on a role that had only been given `DESCRIBE`.
- **Diagnosis:** listing grants for the database showed the analyst with `DESCRIBE` only. Listing grants filtered to the analyst returned `ALL, DESCRIBE`: AWS folds the database's `IAM_ALLOWED_PRINCIPALS` grant into each role's result.
- **The real problem underneath:** that `IAM_ALLOWED_PRINCIPALS ALL` grant (the account default for new databases) meant any role with Glue IAM permissions could create tables in the curated database without Lake Formation.
- **Changed:** the grant is revoked for the curated database only, inside Terraform. The account-wide default is untouched, so other projects in the account are unaffected. The pipeline still builds every table, and the plan now shows no changes.
- **Also:** the first version of that revoke command had a shell precedence mistake (`a || b && exit 1` exits even when `a` succeeds). Rewritten so it succeeds if the grant is removed now or was already gone.
- **Lesson:** a diff that never goes away is worth investigating, not suppressing with `ignore_changes`. This one hid a real access gap.

### Missing pages returned 403, not 404
- **Seen:** a request for a page that does not exist returned 403 through CloudFront.
- **Why:** S3 answers a missing object with 403 when the caller is not allowed to list the bucket. That would have hidden broken links from the error report (F6).
- **Changed:** CloudFront (and only this distribution) may list the site bucket, so missing pages are true 404s. Direct access to the bucket still returns 403 (N7).

### Spark tests would not run on a laptop
- **Seen:** first no Java runtime; then `PYTHON_VERSION_MISMATCH` (Spark workers used Python 3.15, the driver 3.11); then one timestamp two hours out.
- **Why:** Spark's workers pick up the system Python unless told otherwise; and `collect()` converts timestamps to the local timezone of the machine, even when the Spark session is set to UTC.
- **Changed:** Java 17 installed to match CI; the test setup pins the workers to the test's own Python and runs in UTC, as Glue does. 12 of 12 pass.
- **Lesson:** a test that passes in CI and fails on a laptop is usually the environment. Make the test set its own environment.

### Real traffic did not come from the expected edge location
- **Seen:** on the day-one checks the laptop was served from Tel Aviv (TLV55). On build day the same laptop was served from Johannesburg (JNB51), with a few requests through Lagos (LOS).
- **Why:** CloudFront routes each request to the edge location with the best latency at that moment, and that changes.
- **Changed:** the reports use the edge location recorded in each log line, never an assumption.

### First backfill stopped by its own privacy check
- **Seen:** the first run of the backfill failed on day one. A data quality rule, "no IP-shaped text in the user agent", found matches.
- **Why:** the rule was wrong, not the data. Ordinary browser user agents contain version numbers such as `Chrome/131.0.0.0`, which look exactly like an IPv4 address.
- **Changed:** the check now asks the precise question. While the raw address is still known, each row is flagged if any kept text column (user agent, path, referrer, query parameter names) contains that request's own IP, and the rule requires zero flagged rows. A test covers both cases: a browser version is not flagged; an IP in a path or referrer is.
- **Good news inside the failure:** the safety net worked as designed. Nothing was written, Step Functions caught the error, and the failure alarm reached the alerts queue 70 seconds after the run stopped (N5 requires 15 minutes).
- **Lesson:** a pattern match is a proxy for the question you mean. Where the real value is available, check against it.

### Shared query results would have undone the column restriction
- **Seen (while writing the N2 test):** the analyst and data engineer roles used the same Athena workgroup, with one results location both could read.
- **Why it mattered:** Lake Formation stops the analyst selecting `visitor_id`, but Athena writes every query's result to S3. An analyst could have opened the result file of an engineer's query and read the identifiers anyway.
- **Changed:** each role has its own workgroup, with results under its own prefix, and may use only that workgroup and prefix. Both roles also lost catalog access to the clean layer, which they never needed. The N2 test now includes "analyst cannot open the engineer's query results".
- **Lesson:** column-level security covers the table, not the copies a query engine makes. Follow the data to every place it lands.

### Quarantined lines masked IPv4 but not IPv6
- **Seen (while writing the N1 test):** rejected log lines are kept for diagnosis with addresses masked, but the mask matched IPv4 only. A malformed line from an IPv6 visitor would have kept the full address.
- **Changed:** the line's own client address is replaced first, then anything shaped like an IPv4 or IPv6 address. The IPv6 pattern needs `::` or all eight groups, so log times such as `21:59:16` are not mangled. Tests cover IPv6 in both a parseable and a truncated line.
- **Lesson:** test privacy rules with both address families. Synthetic data that only produces one family will never find this.

### The privacy scan flagged a coincidence, and had a hidden limit
- **Seen:** the first N1 scan reported raw client addresses in `client_network`.
- **Diagnosis:** all 29,431 distinct values were correct /24 or /48 network addresses. 330 of them equalled a raw address because the generator sometimes produced a host address ending in `.0`, which is the same as its own network. That reveals nothing beyond the network.
- **Changed:** for `client_network` the test now checks that every value is a network address; every other text column is still compared against the real raw addresses. The scan also had a `LIMIT 5000` that could silently drop matches; removed.
- **Lesson:** when a privacy check fails, prove whether it is a leak before changing either the data or the test. Then make the test ask the right question for each column.

### Two planted answers missed at first, both in the comparison, not the platform
- **Seen:** the first truth check matched requests, bots, broken links, the incident and the experiment effect, but failed on bytes by country (up to 2.1% high, US only) and on visitor counts (one visitor short, one day, one group).
- **Bytes, diagnosed:** the generator's `bytes_by_country` counts human visitors only. Known crawlers are generated in the US and scripted bots in four countries, so the platform's all-traffic figure was correctly higher. Compared with the platform's human-only bytes, every day and country matches exactly.
- **Visitors, diagnosed:** a visitor is an IP and user agent pair, on the site and in the platform. Synthetic IPv4 addresses come from a pool of about four million, so two generated sessions occasionally draw the same pair, and are then one visitor to any system. The generator now also records distinct visitors. That change uses no randomness: all 168 regenerated log files were checked byte-identical (decompressed) to the ones processed, and no existing truth value changed. The platform matches the distinct counts exactly; there was one shared pair in the week.
- **Not changed:** no tolerance was loosened. Both fixes made the test compare like with like, and both explanations were proven before the test was changed.
- **Lesson:** the answer key is code too, and can be wrong. Treat a mismatch as a question about both sides.

### The re-run test could not read one table
- **Seen:** the N4 snapshot (row count and checksum per table) failed on the request table, which has an array column that cannot be cast to text.
- **Changed:** stopped the re-run before Glue started (nothing written), joined array columns into text in the snapshot, retook it and restarted.

### Re-running a day changed two report tables
- **Seen:** the first N4 test re-processed a day and compared every table by row count and checksum. Nine of eleven tables were identical, including the 184,389-row request table. Two report tables kept their row counts but changed content.
- **Why:** both hold response-time percentiles, computed with Athena's `approx_percentile`. It uses a sketch that can give slightly different values on each run. Byte totals were ruled out: they are integer sums, and another table built from them was identical.
- **Changed:** exact percentiles (nearest rank: sort the values, take the one at position ceil(p x n)). At this volume, at most about 185,000 values per group, the cost is negligible. The report tables for all eight days were rebuilt from the unchanged request table, then the N4 test was run again from a fresh snapshot.
- **Lesson:** "re-runnable" means deterministic, not just "no duplicates". An approximate function quietly breaks that, and only a checksum comparison shows it.
- **Second attempt found one more:** with exact percentiles, ten of eleven tables were identical, but the cost table's checksum flipped back to its earlier value. It summed per-edge decimal GB values from another report table, and decimal addition can round differently depending on order. It now totals whole bytes per pricing region from the request table, then multiplies by the price once. The test was repeated on two days (12 and 13 October), since a fault that shows only sometimes can pass a single re-run by luck.
