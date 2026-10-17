# D6: Step Functions orchestrates Glue, Athena SQL and publishing; EventBridge Scheduler starts it.

resource "aws_athena_workgroup" "pipeline" {
  name          = var.name
  force_destroy = true
  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = false
    # A runaway query cannot scan more than 10 GB (about $0.05).
    bytes_scanned_cutoff_per_query = 10737418240
    engine_version { selected_engine_version = "Athena engine version 3" }
    result_configuration {
      output_location = "s3://${module.athena.id}/results/"
      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = aws_kms_key.data.arn
      }
    }
  }
}

resource "aws_glue_catalog_database" "curated" {
  name         = local.curated_db
  description  = "Star schema and report tables. Governed by Lake Formation (D9)."
  location_uri = "s3://${module.lake.id}/curated"
  # No IAM-only default for new tables: access to every table here is granted in Lake Formation.
  create_table_default_permission {
    permissions = []
    principal { data_lake_principal_identifier = "IAM_ALLOWED_PRINCIPALS" }
  }
}

data "archive_file" "pipeline" {
  type        = "zip"
  output_path = "${path.module}/.build/pipeline.zip"
  source {
    content  = file("${path.module}/../pipeline/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../pipeline/publish.py")
    filename = "publish.py"
  }
  dynamic "source" {
    for_each = fileset("${path.module}/../sql", "*.sql")
    content {
      content  = file("${path.module}/../sql/${source.value}")
      filename = "sql/${source.value}"
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name               = "${var.name}-pipeline"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

locals {
  arn_prefix = "arn:${data.aws_partition.current.partition}"
  glue_arns = [
    "${local.arn_prefix}:glue:${var.region}:${local.account_id}:catalog",
    aws_glue_catalog_database.clean.arn,
    aws_glue_catalog_database.curated.arn,
    "${local.arn_prefix}:glue:${var.region}:${local.account_id}:table/${local.clean_db}/*",
    "${local.arn_prefix}:glue:${var.region}:${local.account_id}:table/${local.curated_db}/*",
  ]
}

resource "aws_iam_role_policy" "pipeline" {
  name = "pipeline"
  role = aws_iam_role.pipeline.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid    = "Athena", Effect = "Allow",
        Action = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:GetWorkGroup"],
      Resource = aws_athena_workgroup.pipeline.arn },
      { Sid = "Catalog", Effect = "Allow",
        Action = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables", "glue:CreateTable",
        "glue:UpdateTable", "glue:DeleteTable", "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition"],
      Resource = local.glue_arns },
      { Sid = "LakeFormation", Effect = "Allow", Action = ["lakeformation:GetDataAccess"], Resource = "*" },
      { Sid = "Results", Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:GetBucketLocation", "s3:ListBucket"],
      Resource = [module.athena.arn, "${module.athena.arn}/*"] },
      { Sid = "ReadClean", Effect = "Allow", Action = ["s3:GetObject"], Resource = "${module.lake.arn}/clean/*" },
      # Athena writes Iceberg metadata and data for the curated tables with this role's
      # own credentials, so the one writer of those tables needs S3 access as well as
      # its Lake Formation grants.
      { Sid = "WriteCurated", Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"],
      Resource = "${module.lake.arn}/curated/*" },
      { Sid = "ListLake", Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation"], Resource = module.lake.arn },
      { Sid = "Seeds", Effect = "Allow", Action = ["s3:GetObject", "s3:ListBucket"],
      Resource = [module.artifacts.arn, "${module.artifacts.arn}/seeds/*"] },
      { Sid = "Dashboard", Effect = "Allow", Action = ["s3:PutObject"], Resource = "${module.site.arn}/insights/*" },
      { Sid = "Refresh", Effect = "Allow", Action = ["cloudfront:CreateInvalidation"], Resource = aws_cloudfront_distribution.site.arn },
      { Sid = "Kms", Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = aws_kms_key.data.arn },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "pipeline_xray" {
  role       = aws_iam_role.pipeline.name
  policy_arn = "${local.arn_prefix}:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy_attachment" "pipeline_logs" {
  role       = aws_iam_role.pipeline.name
  policy_arn = "${local.arn_prefix}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "pipeline" {
  name              = "/aws/lambda/${var.name}-pipeline"
  kms_key_id        = aws_kms_key.data.arn
  retention_in_days = 14
}

resource "aws_lambda_function" "pipeline" {
  function_name    = "${var.name}-pipeline"
  role             = aws_iam_role.pipeline.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = data.archive_file.pipeline.output_path
  source_code_hash = data.archive_file.pipeline.output_base64sha256
  memory_size      = 256
  timeout          = 600
  kms_key_arn      = aws_kms_key.data.arn
  tracing_config { mode = "Active" }
  environment {
    variables = {
      WORKGROUP        = aws_athena_workgroup.pipeline.name
      CLEAN_DB         = local.clean_db
      CURATED_DB       = local.curated_db
      LAKE_BUCKET      = module.lake.id
      ARTIFACTS_BUCKET = module.artifacts.id
      SITE_BUCKET      = module.site.id
      DISTRIBUTION_ID  = aws_cloudfront_distribution.site.id
    }
  }
  depends_on = [aws_cloudwatch_log_group.pipeline]
}

# --- Alerts (N5) ---------------------------------------------------------------
resource "aws_sns_topic" "alerts" {
  name              = "${var.name}-alerts"
  kms_master_key_id = aws_kms_key.data.arn
}

resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AwsServicesPublish"
      Effect    = "Allow"
      Principal = { Service = ["budgets.amazonaws.com", "cloudwatch.amazonaws.com"] }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.alerts.arn
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

# A queue on the topic keeps every alert, so tests can prove one was sent and how fast.
resource "aws_sqs_queue" "alerts" {
  name                      = "${var.name}-alerts"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue_policy" "alerts" {
  queue_url = aws_sqs_queue.alerts.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.alerts.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_sns_topic.alerts.arn } }
    }]
  })
}

resource "aws_sns_topic_subscription" "alerts_queue" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.alerts.arn
}

# --- State machine ---------------------------------------------------------------
locals {
  lambda_retry = [{
    ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"]
    IntervalSeconds = 5, MaxAttempts = 3, BackoffRate = 2
  }]
  fail_over = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "Notify" }]
  invoke    = "arn:${data.aws_partition.current.partition}:states:::lambda:invoke"
  definition = {
    Comment = "Process CloudFront logs for one or more days, then publish the dashboard."
    StartAt = "Resolve"
    States = {
      Resolve = {
        Type           = "Task", Resource = local.invoke
        Parameters     = { FunctionName = aws_lambda_function.pipeline.arn, Payload = { action = "resolve", "input.$" = "$" } }
        ResultSelector = { "days.$" = "$.Payload.days" }
        ResultPath     = "$.plan", Retry = local.lambda_retry, Catch = local.fail_over, Next = "Ensure"
      }
      Ensure = {
        Type       = "Task", Resource = local.invoke
        Parameters = { FunctionName = aws_lambda_function.pipeline.arn, Payload = { action = "ensure" } }
        ResultPath = null, Retry = local.lambda_retry, Catch = local.fail_over, Next = "EachDay"
      }
      EachDay = {
        Type           = "Map"
        ItemsPath      = "$.plan.days"
        ItemSelector   = { "day.$" = "$$.Map.Item.Value" }
        MaxConcurrency = 1
        ItemProcessor = {
          ProcessorConfig = { Mode = "INLINE" }
          StartAt         = "Process"
          States = {
            Process = {
              Type       = "Task", Resource = "arn:${data.aws_partition.current.partition}:states:::glue:startJobRun.sync"
              Parameters = { JobName = aws_glue_job.process_logs.name, Arguments = { "--day.$" = "$.day" } }
              ResultPath = null
              Retry      = [{ ErrorEquals = ["Glue.ConcurrentRunsExceededException"], IntervalSeconds = 30, MaxAttempts = 5, BackoffRate = 1.5 }]
              Next       = "LoadFact"
            }
            LoadFact = {
              Type       = "Task", Resource = local.invoke
              Parameters = { FunctionName = aws_lambda_function.pipeline.arn, Payload = { action = "sql", name = "fact", "day.$" = "$.day" } }
              ResultPath = null, Retry = local.lambda_retry, Next = "Aggregate"
            }
            Aggregate = {
              Type       = "Task", Resource = local.invoke
              Parameters = { FunctionName = aws_lambda_function.pipeline.arn, Payload = { action = "sql", name = "aggregates", "day.$" = "$.day" } }
              ResultPath = null, Retry = local.lambda_retry, Next = "Reconcile"
            }
            Reconcile = {
              Type           = "Task", Resource = local.invoke
              Parameters     = { FunctionName = aws_lambda_function.pipeline.arn, Payload = { action = "reconcile", "day.$" = "$.day" } }
              ResultSelector = { "layers.$" = "$.Payload.layers" }
              Retry          = local.lambda_retry, End = true
            }
          }
        }
        ResultPath = "$.results", Catch = local.fail_over, Next = "Publish"
      }
      Publish = {
        Type           = "Task", Resource = local.invoke
        Parameters     = { FunctionName = aws_lambda_function.pipeline.arn, Payload = { action = "publish" } }
        ResultSelector = { "published.$" = "$.Payload" }
        ResultPath     = "$.publish", Retry = local.lambda_retry, Catch = local.fail_over, Next = "Done"
      }
      Done = { Type = "Succeed" }
      Notify = {
        Type = "Task", Resource = "arn:${data.aws_partition.current.partition}:states:::sns:publish"
        Parameters = {
          TopicArn    = aws_sns_topic.alerts.arn
          Subject     = "${var.name}: pipeline run failed"
          "Message.$" = "States.Format('Execution {} failed. {}: {}', $$.Execution.Name, $.error.Error, $.error.Cause)"
        }
        ResultPath = null, Next = "Failed"
      }
      Failed = { Type = "Fail", Error = "PipelineFailed", Cause = "See the alert message and the execution history." }
    }
  }
}

resource "aws_iam_role" "states" {
  name = "${var.name}-states"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "states.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "states" {
  name = "orchestrate"
  role = aws_iam_role.states.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.pipeline.arn },
      { Effect = "Allow", Action = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"],
      Resource = aws_glue_job.process_logs.arn },
      { Effect = "Allow", Action = ["sns:Publish"], Resource = aws_sns_topic.alerts.arn },
      { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = aws_kms_key.data.arn },
      { Effect = "Allow", Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules",
      "xray:GetSamplingTargets"], Resource = "*" },
      { Effect = "Allow", Action = ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery",
        "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"],
      Resource = "*" },
    ]
  })
}

resource "aws_cloudwatch_log_group" "states" {
  name              = "/aws/vendedlogs/states/${var.name}"
  kms_key_id        = aws_kms_key.data.arn
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "pipeline" {
  name       = "${var.name}-pipeline"
  role_arn   = aws_iam_role.states.arn
  definition = jsonencode(local.definition)
  logging_configuration {
    log_destination = "${aws_cloudwatch_log_group.states.arn}:*"
    # Execution data is days and row counts only; no personal data passes through.
    include_execution_data = true
    level                  = "ALL"
  }
  tracing_configuration { enabled = true }
}

# Anything that fails outside the catch blocks (a timeout, for example) still alerts.
resource "aws_cloudwatch_metric_alarm" "pipeline_failed" {
  alarm_name          = "${var.name}-pipeline-failed"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.pipeline.arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_iam_role" "scheduler" {
  name = "${var.name}-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } } }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "start-pipeline"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "states:StartExecution", Resource = aws_sfn_state_machine.pipeline.arn }]
  })
}

# N5: yesterday's data is processed at 05:00 UTC, ready before 06:00.
resource "aws_scheduler_schedule" "daily" {
  name                         = "${var.name}-daily"
  schedule_expression          = "cron(0 5 * * ? *)"
  schedule_expression_timezone = "UTC"
  state                        = var.schedule_enabled ? "ENABLED" : "DISABLED"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_sfn_state_machine.pipeline.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = "{}"
  }
}
