# Two people-facing roles, assumable from this account, used to prove N2.
data "aws_iam_policy_document" "assume_from_account" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${local.account_id}:root"]
    }
  }
}

# Each role queries in its own workgroup, with results under its own prefix. A shared
# results location would let an analyst open the result file of an engineer's query and
# read visitor_id, getting round the column restriction (found during the build).
locals {
  people = toset(["analyst", "data-engineer"])
}

resource "aws_athena_workgroup" "people" {
  for_each      = local.people
  name          = "${var.name}-${each.key}"
  force_destroy = true
  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = false
    bytes_scanned_cutoff_per_query     = 10737418240
    engine_version { selected_engine_version = "Athena engine version 3" }
    result_configuration {
      output_location = "s3://${module.athena.id}/people/${each.key}/"
      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = aws_kms_key.data.arn
      }
    }
  }
}

data "aws_iam_policy_document" "query" {
  for_each = local.people
  statement {
    sid       = "Athena"
    actions   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:GetWorkGroup"]
    resources = [aws_athena_workgroup.people[each.key].arn]
  }
  # The curated database only: the clean layer is for the pipeline.
  statement {
    sid     = "Catalog"
    actions = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables", "glue:GetPartitions"]
    resources = [
      "${local.arn_prefix}:glue:${var.region}:${local.account_id}:catalog",
      aws_glue_catalog_database.curated.arn,
      "${local.arn_prefix}:glue:${var.region}:${local.account_id}:table/${local.curated_db}/*",
    ]
  }
  statement {
    sid       = "LakeFormation"
    actions   = ["lakeformation:GetDataAccess"]
    resources = ["*"]
  }
  statement {
    sid       = "OwnResults"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${module.athena.arn}/people/${each.key}/*"]
  }
  statement {
    sid       = "ResultsBucket"
    actions   = ["s3:GetBucketLocation", "s3:ListBucket"]
    resources = [module.athena.arn]
  }
  statement {
    sid       = "Kms"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.data.arn]
  }
}

resource "aws_iam_role" "analyst" {
  name               = "${var.name}-analyst"
  assume_role_policy = data.aws_iam_policy_document.assume_from_account.json
}

resource "aws_iam_role_policy" "analyst" {
  name   = "query"
  role   = aws_iam_role.analyst.id
  policy = data.aws_iam_policy_document.query["analyst"].json
}

resource "aws_iam_role" "engineer" {
  name               = "${var.name}-data-engineer"
  assume_role_policy = data.aws_iam_policy_document.assume_from_account.json
}

resource "aws_iam_role_policy" "engineer" {
  name   = "query"
  role   = aws_iam_role.engineer.id
  policy = data.aws_iam_policy_document.query["data-engineer"].json
}
