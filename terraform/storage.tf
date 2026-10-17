# raw:       CloudFront logs as delivered. Contains IP addresses, so it expires (N1).
# lake:      clean/, quarantine/, curated/ Iceberg tables. No raw IP addresses.
# athena:    query results; short-lived.
# site:      the storefront and the insights dashboard, served only through CloudFront.
# artifacts: Glue scripts and seed data.

module "raw" {
  source      = "./modules/bucket"
  name        = local.bucket.raw
  kms_key_arn = aws_kms_key.data.arn
  expire_days = var.raw_retention_days
  policy_statements = [{
    Sid       = "CloudFrontLogDelivery"
    Effect    = "Allow"
    Principal = { Service = "delivery.logs.amazonaws.com" }
    Action    = "s3:PutObject"
    Resource  = "arn:${data.aws_partition.current.partition}:s3:::${local.bucket.raw}/cloudfront/*"
    Condition = {
      StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control", "aws:SourceAccount" = local.account_id }
      ArnLike      = { "aws:SourceArn" = "arn:${data.aws_partition.current.partition}:logs:us-east-1:${local.account_id}:delivery-source:*" }
    }
  }]
}

module "lake" {
  source      = "./modules/bucket"
  name        = local.bucket.lake
  kms_key_arn = aws_kms_key.data.arn
}

module "athena" {
  source      = "./modules/bucket"
  name        = local.bucket.athena
  kms_key_arn = aws_kms_key.data.arn
  expire_days = 7
}

module "artifacts" {
  source      = "./modules/bucket"
  name        = local.bucket.artifacts
  kms_key_arn = aws_kms_key.data.arn
}

# Public content, so S3-managed encryption; readable only by this distribution (N7).
module "site" {
  source = "./modules/bucket"
  name   = local.bucket.site
  policy_statements = [{
    Sid       = "CloudFrontReads"
    Effect    = "Allow"
    Principal = { Service = "cloudfront.amazonaws.com" }
    Action    = "s3:GetObject"
    Resource  = "arn:${data.aws_partition.current.partition}:s3:::${local.bucket.site}/*"
    Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.site.arn } }
    }, {
    # Without list access S3 answers a missing page with 403, which would hide broken
    # links from the error reports (F6). With it, a missing page is a true 404.
    Sid       = "CloudFrontSeesMissingPages"
    Effect    = "Allow"
    Principal = { Service = "cloudfront.amazonaws.com" }
    Action    = "s3:ListBucket"
    Resource  = "arn:${data.aws_partition.current.partition}:s3:::${local.bucket.site}"
    Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.site.arn } }
  }]
}

locals {
  site_dir = "${path.module}/../site"
  content_types = {
    html = "text/html; charset=utf-8", css = "text/css", js = "text/javascript", json = "application/json",
    svg  = "image/svg+xml", png = "image/png", jpg = "image/jpeg", webp = "image/webp", ico = "image/x-icon", txt = "text/plain"
  }
}

resource "aws_s3_object" "site" {
  for_each     = fileset(local.site_dir, "**")
  bucket       = module.site.id
  key          = each.value
  source       = "${local.site_dir}/${each.value}"
  etag         = filemd5("${local.site_dir}/${each.value}")
  content_type = lookup(local.content_types, reverse(split(".", each.value))[0], "application/octet-stream")
}

resource "aws_s3_object" "seeds" {
  for_each = fileset("${path.module}/../seeds", "*.csv")
  bucket   = module.artifacts.id
  key      = "seeds/${trimsuffix(each.value, ".csv")}/${each.value}"
  source   = "${path.module}/../seeds/${each.value}"
  etag     = filemd5("${path.module}/../seeds/${each.value}")
}
