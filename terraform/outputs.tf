output "site_url" { value = "https://${aws_cloudfront_distribution.site.domain_name}" }
output "dashboard_url" { value = "https://${aws_cloudfront_distribution.site.domain_name}/insights/" }
output "distribution_id" { value = aws_cloudfront_distribution.site.id }
output "api_function_url" {
  description = "Direct calls must be refused (403); only CloudFront may call it."
  value       = aws_lambda_function_url.api.function_url
}
output "raw_bucket" { value = module.raw.id }
output "lake_bucket" { value = module.lake.id }
output "site_bucket" { value = module.site.id }
output "state_machine_arn" { value = aws_sfn_state_machine.pipeline.arn }
output "glue_job" { value = aws_glue_job.process_logs.name }
output "workgroup" { value = aws_athena_workgroup.pipeline.name }
output "clean_db" { value = local.clean_db }
output "curated_db" { value = local.curated_db }
output "analyst_role_arn" { value = aws_iam_role.analyst.arn }
output "engineer_role_arn" { value = aws_iam_role.engineer.arn }
output "alerts_queue_url" { value = aws_sqs_queue.alerts.id }
output "ci_role_arn" { value = aws_iam_role.ci.arn }
output "viewer_request_function" { value = aws_cloudfront_function.viewer_request.name }
output "people_workgroups" { value = { for k, w in aws_athena_workgroup.people : k => w.name } }
