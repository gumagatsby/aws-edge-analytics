# D9: Lake Formation governs the curated database. Analysts see report tables and
# the fact table without its visitor identifier; data engineers see everything.

# Keeps the account's existing defaults (IAM-only for new databases and tables), so
# other projects in the account are unaffected; only adds the deploying identity as admin.
resource "aws_lakeformation_data_lake_settings" "this" {
  admins = [data.aws_iam_session_context.current.issuer_arn]
  create_database_default_permissions {
    permissions = ["ALL"]
    principal   = "IAM_ALLOWED_PRINCIPALS"
  }
  create_table_default_permissions {
    permissions = ["ALL"]
    principal   = "IAM_ALLOWED_PRINCIPALS"
  }
}

data "aws_iam_session_context" "current" {
  arn = data.aws_caller_identity.current.arn
}

# Lake Formation reads and writes the curated location with this role on behalf of
# whoever it has granted access.
resource "aws_iam_role" "lakeformation" {
  name = "${var.name}-lakeformation"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lakeformation.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "lakeformation" {
  name = "curated-location"
  role = aws_iam_role.lakeformation.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "${module.lake.arn}/curated/*" },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = module.lake.arn },
      { Effect = "Allow", Action = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"], Resource = aws_kms_key.data.arn },
    ]
  })
}

resource "aws_lakeformation_resource" "curated" {
  arn                     = "${module.lake.arn}/curated"
  role_arn                = aws_iam_role.lakeformation.arn
  use_service_linked_role = false
  depends_on              = [aws_lakeformation_data_lake_settings.this]
}

# The account default gives IAM_ALLOWED_PRINCIPALS ALL on every new database, which
# would let any role with Glue IAM permissions create tables here outside Lake
# Formation. Removed for this database only; the account default stays as it is.
# (It also made the provider read ALL back into each role's database grant.)
resource "terraform_data" "curated_lf_only" {
  triggers_replace = [aws_glue_catalog_database.curated.id]
  provisioner "local-exec" {
    # Succeeds if the grant is revoked now or was already gone (re-runs).
    command = <<-EOT
      aws lakeformation revoke-permissions --region ${var.region} \
        --principal DataLakePrincipalIdentifier=IAM_ALLOWED_PRINCIPALS --permissions ALL \
        --resource '{"Database":{"Name":"${aws_glue_catalog_database.curated.name}"}}' \
      || ! aws lakeformation list-permissions --region ${var.region} \
        --resource '{"Database":{"Name":"${aws_glue_catalog_database.curated.name}"}}' \
        --query "PrincipalResourcePermissions[?Principal.DataLakePrincipalIdentifier=='IAM_ALLOWED_PRINCIPALS']" \
        --output text | grep -q .
    EOT
  }
  depends_on = [aws_lakeformation_data_lake_settings.this]
}

# The pipeline builds the curated tables, so it can do anything in this database.
resource "aws_lakeformation_permissions" "pipeline_location" {
  principal   = aws_iam_role.pipeline.arn
  permissions = ["DATA_LOCATION_ACCESS"]
  data_location { arn = aws_lakeformation_resource.curated.arn }
}

resource "aws_lakeformation_permissions" "pipeline_database" {
  principal   = aws_iam_role.pipeline.arn
  permissions = ["CREATE_TABLE", "ALTER", "DROP", "DESCRIBE"]
  database { name = aws_glue_catalog_database.curated.name }
  depends_on = [aws_lakeformation_data_lake_settings.this, terraform_data.curated_lf_only]
}

resource "aws_lakeformation_permissions" "pipeline_tables" {
  principal   = aws_iam_role.pipeline.arn
  permissions = ["ALL"]
  table {
    database_name = aws_glue_catalog_database.curated.name
    wildcard      = true
  }
  depends_on = [aws_lakeformation_data_lake_settings.this]
}

# IAM changes take a few seconds to reach Athena. Without this pause the first
# deployment's set-up query is refused access to S3 (seen on the first build).
resource "time_sleep" "pipeline_policy" {
  create_duration = "20s"
  triggers        = { policy = aws_iam_role_policy.pipeline.policy }
}

# The curated tables are created by the pipeline's own SQL. Running that set-up once
# during deployment means the per-table grants below have tables to point at.
resource "aws_lambda_invocation" "ensure_tables" {
  function_name = aws_lambda_function.pipeline.function_name
  input         = jsonencode({ action = "ensure" })
  triggers      = { sql = filemd5("${path.module}/../sql/ensure.sql") }
  depends_on = [
    aws_lakeformation_permissions.pipeline_location, aws_lakeformation_permissions.pipeline_database,
    aws_lakeformation_permissions.pipeline_tables, time_sleep.pipeline_policy,
  ]
}

locals {
  analyst_tables = [
    "dim_edge_location", "dim_date", "dim_content", "dim_client", "agg_edge_daily", "agg_country_daily",
    "agg_ab_daily", "agg_bots_daily", "agg_errors_daily", "agg_cache_daily", "agg_cost_daily",
  ]
}

resource "aws_lakeformation_permissions" "analyst_database" {
  principal   = aws_iam_role.analyst.arn
  permissions = ["DESCRIBE"]
  database { name = aws_glue_catalog_database.curated.name }
  depends_on = [aws_lakeformation_data_lake_settings.this, terraform_data.curated_lf_only]
}

resource "aws_lakeformation_permissions" "analyst_tables" {
  for_each    = toset(local.analyst_tables)
  principal   = aws_iam_role.analyst.arn
  permissions = ["SELECT", "DESCRIBE"]
  table {
    database_name = aws_glue_catalog_database.curated.name
    name          = each.value
  }
  depends_on = [aws_lambda_invocation.ensure_tables]
}

# N2: analysts can query requests, but never the pseudonymised visitor identifier.
resource "aws_lakeformation_permissions" "analyst_fact" {
  principal   = aws_iam_role.analyst.arn
  permissions = ["SELECT"]
  table_with_columns {
    database_name         = aws_glue_catalog_database.curated.name
    name                  = "fact_request"
    wildcard              = true
    excluded_column_names = ["visitor_id"]
  }
  depends_on = [aws_lambda_invocation.ensure_tables]
}

resource "aws_lakeformation_permissions" "engineer_database" {
  principal   = aws_iam_role.engineer.arn
  permissions = ["DESCRIBE"]
  database { name = aws_glue_catalog_database.curated.name }
  depends_on = [aws_lakeformation_data_lake_settings.this, terraform_data.curated_lf_only]
}

resource "aws_lakeformation_permissions" "engineer_tables" {
  principal   = aws_iam_role.engineer.arn
  permissions = ["SELECT", "DESCRIBE"]
  table {
    database_name = aws_glue_catalog_database.curated.name
    wildcard      = true
  }
  depends_on = [aws_lakeformation_data_lake_settings.this]
}
