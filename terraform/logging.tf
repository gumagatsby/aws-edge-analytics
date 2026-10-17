# D1: CloudFront standard logging (v2) to the raw bucket, as W3C text,
# partitioned by distribution and hour. No delivery charge for S3.
locals {
  log_fields = [
    "date", "time", "timestamp(ms)", "x-edge-location", "sc-bytes", "c-ip", "cs-method", "cs(Host)",
    "cs-uri-stem", "sc-status", "cs(Referer)", "cs(User-Agent)", "cs-uri-query", "cs(Cookie)",
    "x-edge-result-type", "x-edge-request-id", "x-host-header", "cs-protocol", "cs-bytes", "time-taken",
    "x-forwarded-for", "ssl-protocol", "ssl-cipher", "x-edge-response-result-type", "cs-protocol-version",
    "time-to-first-byte", "x-edge-detailed-result-type", "sc-content-type", "sc-content-len", "c-country",
    "asn", "cache-behavior-path-pattern", "viewer-request-log-data",
  ]
}

resource "aws_cloudwatch_log_delivery_source" "cloudfront" {
  provider     = aws.us_east_1
  name         = "${var.name}-cloudfront"
  log_type     = "ACCESS_LOGS"
  resource_arn = aws_cloudfront_distribution.site.arn
}

resource "aws_cloudwatch_log_delivery_destination" "raw" {
  provider      = aws.us_east_1
  name          = "${var.name}-raw"
  output_format = "w3c"
  delivery_destination_configuration {
    destination_resource_arn = "${module.raw.arn}/cloudfront"
  }
}

resource "aws_cloudwatch_log_delivery" "cloudfront" {
  provider                 = aws.us_east_1
  delivery_source_name     = aws_cloudwatch_log_delivery_source.cloudfront.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.raw.arn
  record_fields            = local.log_fields
  s3_delivery_configuration {
    suffix_path                 = "{distributionid}/{yyyy}/{MM}/{dd}/{HH}"
    enable_hive_compatible_path = true
  }
}
