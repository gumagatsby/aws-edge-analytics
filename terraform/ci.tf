# N8: GitHub Actions authenticates with OIDC; there are no stored AWS keys.
# The OIDC provider already exists in the account (shared with other projects).
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "ci" {
  name = "${var.name}-ci"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:*" }
      }
    }]
  })
}

# Read-only: CI runs the deployed edge functions through CloudFront's own test
# runtime and reads pipeline status. It cannot change anything.
resource "aws_iam_role_policy" "ci" {
  name = "verify"
  role = aws_iam_role.ci.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["cloudfront:TestFunction", "cloudfront:DescribeFunction"],
      Resource = [aws_cloudfront_function.viewer_request.arn, aws_cloudfront_function.viewer_response.arn] },
      { Effect = "Allow", Action = ["states:ListExecutions", "states:DescribeExecution"],
      Resource = [aws_sfn_state_machine.pipeline.arn, "${replace(aws_sfn_state_machine.pipeline.arn, ":stateMachine:", ":execution:")}:*"] },
    ]
  })
}
