"""AWS Glue job: process one day of CloudFront access logs.

    raw (S3, W3C text)  ->  clean.requests      (Iceberg, no raw IPs)
                        ->  clean.quarantine    (Iceberg, IPs masked)
                        ->  clean.run_audit     (Iceberg, one row per day and source)

Re-running a day replaces that day's partitions (N4). The run fails, and writes
nothing, if the data-quality ruleset fails or the row counts do not reconcile (N3).
"""
import datetime
import sys
import uuid

import boto3
from awsglue.context import GlueContext
from awsglue.dynamicframe import DynamicFrame
from awsglue.utils import getResolvedOptions
from awsgluedq.transforms import EvaluateDataQuality
from pyspark.context import SparkContext
from pyspark.sql import functions as F

from edge_etl.transform import parse

args = getResolvedOptions(sys.argv, ["JOB_NAME", "day", "raw_bucket", "distribution_id", "clean_db", "hmac_parameter"])
day = datetime.date.fromisoformat(args["day"])
run_id = str(uuid.uuid4())

glue = GlueContext(SparkContext.getOrCreate())
spark = glue.spark_session
spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")
key = boto3.client("ssm").get_parameter(Name=args["hmac_parameter"], WithDecryption=True)["Parameter"]["Value"].encode()
db = f"glue_catalog.{args['clean_db']}"

DQ_RULES = """Rules = [
    IsComplete "request_id",
    IsUnique "request_id",
    IsComplete "event_ts",
    ColumnValues "status" between 99 and 600,
    ColumnValues "edge_code" matches "[A-Z]{3}",
    ColumnValues "bot_class" in ["human", "known_bot", "suspected_bot"],
    ColumnValues "content_group" in ["home", "product", "checkout", "api", "asset", "insights", "other"],
    CustomSql "select count(*) from primary where client_network is not null and client_network not like '%.0' and client_network not like '%:%'" = 0,
    CustomSql "select count(*) from primary where ip_in_text" = 0
]"""

spark.sql(f"""CREATE TABLE IF NOT EXISTS {db}.requests (
    request_id string, event_ts timestamp, day date, hour int, edge_location string, edge_code string,
    client_network string, visitor_id string, country string, asn int, method string, path string,
    query_keys array<string>, tracking_params int, status int, bytes_sent bigint, bytes_received bigint,
    time_taken_s double, ttfb_s double, result_type string, response_result_type string,
    detailed_result_type string, content_type string, http_version string, tls_version string,
    cache_behavior string, ab_new_visitor boolean, stripped_params int, user_agent string,
    referrer_host string, source string, log_file string, ab_group string, content_group string,
    bot_class string, bot_reason string, device_class string)
  USING iceberg PARTITIONED BY (day) TBLPROPERTIES ('format-version'='2', 'write.parquet.compression-codec'='zstd')""")
spark.sql(f"""CREATE TABLE IF NOT EXISTS {db}.quarantine (line string, reason string, log_file string, source string, day date)
  USING iceberg PARTITIONED BY (day) TBLPROPERTIES ('format-version'='2')""")
spark.sql(f"""CREATE TABLE IF NOT EXISTS {db}.run_audit (day date, source string, run_id string, raw_lines bigint,
    clean_rows bigint, quarantined_rows bigint, balanced boolean, finished_at timestamp)
  USING iceberg PARTITIONED BY (day) TBLPROPERTIES ('format-version'='2')""")


def main():
    # CloudFront writes cloudfront/distributionid=<id>/year=/month=/day=/hour=/; the synthetic
    # generator writes the same layout under synthetic/distributionid=synthetic/.
    s3 = boto3.client("s3")
    date_path = f"year={day:%Y}/month={day:%m}/day={day:%d}/"
    sources = {"real": f"cloudfront/distributionid={args['distribution_id']}/{date_path}",
               "synthetic": f"synthetic/distributionid=synthetic/{date_path}"}
    files = {}
    for source, prefix in sources.items():
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=args["raw_bucket"], Prefix=prefix):
            files.setdefault(source, []).extend(f"s3://{args['raw_bucket']}/{o['Key']}" for o in page.get("Contents", []))

    audit = []
    clean_parts, quarantine_parts = [], []
    for source, paths in files.items():
        if not paths:
            continue
        lines = (spark.read.text(paths).withColumn("log_file", F.input_file_name()).withColumn("source", F.lit(source)))
        raw_lines = lines.filter(~F.col("value").startswith("#")).count()
        clean, quarantine = parse(lines, key)
        clean, quarantine = clean.cache(), quarantine.cache()
        n_clean, n_quarantine = clean.count(), quarantine.count()
        audit.append((day, source, run_id, raw_lines, n_clean, n_quarantine, raw_lines == n_clean + n_quarantine))
        clean_parts.append(clean)
        quarantine_parts.append(quarantine.withColumn("day", F.lit(day)))
        print(f"{source}: {len(paths)} files, {raw_lines} lines, {n_clean} clean, {n_quarantine} quarantined")

    if not clean_parts:
        # A day without traffic is recorded as zero rows, so reconciliation still has a row to check.
        (spark.createDataFrame([(day, "real", run_id, 0, 0, 0, True)],
                               "day date, source string, run_id string, raw_lines bigint, clean_rows bigint, "
                               "quarantined_rows bigint, balanced boolean")
              .withColumn("finished_at", F.current_timestamp()).writeTo(f"{db}.run_audit").overwritePartitions())
        print(f"No logs for {day}; recorded an empty run.")
        return

    unbalanced = [a for a in audit if not a[6]]
    if unbalanced:
        raise RuntimeError(f"Row counts do not reconcile: {unbalanced}")

    clean = clean_parts[0]
    for part in clean_parts[1:]:
        clean = clean.unionByName(part)
    quarantine = quarantine_parts[0]
    for part in quarantine_parts[1:]:
        quarantine = quarantine.unionByName(part)

    # Dataset-level checks. A failure stops the run before anything is written.
    dq = EvaluateDataQuality.apply(
        frame=DynamicFrame.fromDF(clean, glue, "clean"),
        ruleset=DQ_RULES,
        publishing_options={"dataQualityEvaluationContext": f"requests_{day:%Y%m%d}",
                            "enableDataQualityResultsPublishing": True,
                            "enableDataQualityCloudWatchMetrics": False},
    ).toDF()
    failed = dq.filter(F.col("Outcome") != "Passed").select("Rule", "FailureReason").collect()
    for row in dq.select("Rule", "Outcome").collect():
        print(f"DQ {row['Outcome']}: {row['Rule']}")
    if failed:
        raise RuntimeError(f"Data quality failed: {[(r['Rule'], r['FailureReason']) for r in failed]}")

    # Every row belongs to the day of the log file it arrived in, so a day's run owns all of
    # its rows and nothing is dropped. event_ts keeps the exact time: a request at 23:59:59.9
    # delivered in the 00:00 file counts towards the next day.
    clean.withColumn("day", F.lit(day)).select(*spark.table(f"{db}.requests").columns) \
        .writeTo(f"{db}.requests").overwritePartitions()
    # A clean re-run can have no quarantined rows; overwritePartitions would then leave the
    # previous run's rows in place, so this table is cleared for the day first.
    spark.sql(f"DELETE FROM {db}.quarantine WHERE day = DATE '{day}'")
    quarantine.select("line", "reason", "log_file", "source", "day").writeTo(f"{db}.quarantine").append()
    (spark.createDataFrame(audit, "day date, source string, run_id string, raw_lines bigint, clean_rows bigint, "
                                  "quarantined_rows bigint, balanced boolean")
          .withColumn("finished_at", F.current_timestamp())
          .writeTo(f"{db}.run_audit").overwritePartitions())
    print(f"Done: {day} run {run_id}")


main()
