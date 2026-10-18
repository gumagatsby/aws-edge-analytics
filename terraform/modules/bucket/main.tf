# A private bucket: public access blocked, ACLs disabled, TLS required, encrypted,
# optionally expiring objects. Extra policy statements are merged in.
terraform {
  required_version = ">= 1.10.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

variable "name" { type = string }
variable "kms_key_arn" {
  type    = string
  default = null
}
variable "expire_days" {
  type    = number
  default = null
}
variable "policy_statements" {
  description = "Additional bucket policy statements, as a list of objects in IAM JSON form."
  type        = list(any)
  default     = []
}

resource "aws_s3_bucket" "this" {
  bucket = var.name
  # Teardown is part of the brief (N9); nothing here is a system of record.
  force_destroy = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  bucket = aws_s3_bucket.this.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket                  = aws_s3_bucket.this.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn == null ? "AES256" : "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = var.kms_key_arn != null
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
  dynamic "rule" {
    for_each = var.expire_days == null ? [] : [var.expire_days]
    content {
      id     = "expire"
      status = "Enabled"
      filter {}
      expiration { days = rule.value }
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  bucket = aws_s3_bucket.this.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.this.arn, "${aws_s3_bucket.this.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }], var.policy_statements)
  })
  depends_on = [aws_s3_bucket_public_access_block.this]
}

output "id" { value = aws_s3_bucket.this.id }
output "arn" { value = aws_s3_bucket.this.arn }
output "regional_domain_name" { value = aws_s3_bucket.this.bucket_regional_domain_name }
