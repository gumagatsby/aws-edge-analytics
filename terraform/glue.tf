# D4, D5: one Glue Spark job turns raw logs into the clean layer, with data-quality rules.
resource "aws_glue_catalog_database" "clean" {
  name         = local.clean_db
  description  = "Parsed, pseudonymised requests; quarantine; run audit. No raw IP addresses."
  location_uri = "s3://${module.lake.id}/clean"
}

resource "random_password" "hmac" {
  length  = 48
  special = false
}

# The pseudonymisation key (D8). Standard parameters cost nothing; the value is
# encrypted with the project key and is only readable by the Glue job role.
resource "aws_ssm_parameter" "hmac" {
  name        = "/${var.name}/visitor-hmac-key"
  description = "HMAC key for visitor identifiers. Rotating it starts new visitor ids."
  type        = "SecureString"
  key_id      = aws_kms_key.data.arn
  value       = random_password.hmac.result
}

# The zip must contain the edge_etl/ package directory, so it is rebuilt with that prefix.
data "archive_file" "etl_pkg" {
  type        = "zip"
  output_path = "${path.module}/.build/edge_etl_pkg.zip"
  dynamic "source" {
    for_each = fileset("${path.module}/../glue/edge_etl", "*.py")
    content {
      content  = file("${path.module}/../glue/edge_etl/${source.value}")
      filename = "edge_etl/${source.value}"
    }
  }
}

resource "aws_s3_object" "etl_script" {
  bucket = module.artifacts.id
  key    = "glue/process_logs.py"
  source = "${path.module}/../glue/process_logs.py"
  etag   = filemd5("${path.module}/../glue/process_logs.py")
}

resource "aws_s3_object" "etl_lib" {
  bucket = module.artifacts.id
  key    = "glue/edge_etl.zip"
  source = data.archive_file.etl_pkg.output_path
  etag   = data.archive_file.etl_pkg.output_md5
}

resource "aws_iam_role" "glue" {
  name = "${var.name}-glue"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "glue.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "glue" {
  name = "process-logs"
  role = aws_iam_role.glue.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "ReadRaw", Effect = "Allow", Action = ["s3:GetObject"], Resource = "${module.raw.arn}/*" },
      { Sid = "ListRaw", Effect = "Allow", Action = ["s3:ListBucket"], Resource = module.raw.arn },
      { Sid = "ReadArtifacts", Effect = "Allow", Action = ["s3:GetObject"], Resource = "${module.artifacts.arn}/glue/*" },
      { Sid = "WriteClean", Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      Resource = "${module.lake.arn}/clean/*" },
      { Sid = "ListLake", Effect = "Allow", Action = ["s3:ListBucket"], Resource = module.lake.arn },
      { Sid = "Catalog", Effect = "Allow",
        Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:CreateTable", "glue:UpdateTable",
        "glue:GetPartitions"],
        Resource = ["arn:${data.aws_partition.current.partition}:glue:${var.region}:${local.account_id}:catalog",
          aws_glue_catalog_database.clean.arn,
      "arn:${data.aws_partition.current.partition}:glue:${var.region}:${local.account_id}:table/${local.clean_db}/*"] },
      { Sid = "DataQuality", Effect = "Allow", Action = ["glue:PublishDataQuality"], Resource = "*" },
      { Sid = "Key", Effect = "Allow", Action = ["ssm:GetParameter"], Resource = aws_ssm_parameter.hmac.arn },
      { Sid = "Kms", Effect = "Allow", Action = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"], Resource = aws_kms_key.data.arn },
      { Sid = "Logs", Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents",
        "logs:AssociateKmsKey"],
      Resource = "arn:${data.aws_partition.current.partition}:logs:${var.region}:${local.account_id}:log-group:/aws-glue/*" },
    ]
  })
}

# Encrypts what Glue itself writes: S3 output, CloudWatch logs and job bookmarks.
resource "aws_glue_security_configuration" "this" {
  name = var.name
  encryption_configuration {
    s3_encryption {
      s3_encryption_mode = "SSE-KMS"
      kms_key_arn        = aws_kms_key.data.arn
    }
    cloudwatch_encryption {
      cloudwatch_encryption_mode = "SSE-KMS"
      kms_key_arn                = aws_kms_key.data.arn
    }
    job_bookmarks_encryption {
      job_bookmarks_encryption_mode = "CSE-KMS"
      kms_key_arn                   = aws_kms_key.data.arn
    }
  }
}

resource "aws_glue_job" "process_logs" {
  name                   = "${var.name}-process-logs"
  security_configuration = aws_glue_security_configuration.this.name
  role_arn               = aws_iam_role.glue.arn
  glue_version           = "5.0"
  worker_type            = "G.1X"
  number_of_workers      = 2
  timeout                = 30
  max_retries            = 0
  command {
    name            = "glueetl"
    script_location = "s3://${module.artifacts.id}/${aws_s3_object.etl_script.key}"
    python_version  = "3"
  }
  default_arguments = {
    "--extra-py-files"                   = "s3://${module.artifacts.id}/${aws_s3_object.etl_lib.key}"
    "--datalake-formats"                 = "iceberg"
    "--enable-continuous-cloudwatch-log" = "true"
    "--raw_bucket"                       = module.raw.id
    "--distribution_id"                  = aws_cloudfront_distribution.site.id
    "--clean_db"                         = local.clean_db
    "--hmac_parameter"                   = aws_ssm_parameter.hmac.name
    "--day"                              = "1970-01-01"
    # Iceberg tables in the Glue Data Catalog, written through S3FileIO.
    "--conf" = join(" --conf ", [
      "spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
      "spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog",
      "spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog",
      "spark.sql.catalog.glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO",
      "spark.sql.catalog.glue_catalog.warehouse=s3://${module.lake.id}/clean",
    ])
  }
}
