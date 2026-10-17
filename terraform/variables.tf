variable "region" {
  description = "Region for all data (N6: data stays in the UK)."
  type        = string
  default     = "eu-west-2"
}

variable "name" {
  description = "Prefix for resource names."
  type        = string
  default     = "edge-analytics"
}

variable "github_oidc_subject" {
  description = <<-EOT
    Subject prefix of the repository allowed to assume the CI role through OIDC. GitHub
    issues immutable subjects (owner and repository IDs), so a renamed or re-created
    repository with the same name cannot assume the role. Read it with:
    gh api repos/OWNER/NAME/actions/oidc/customization/sub --jq .sub_claim_prefix
  EOT
  type        = string
  default     = "repo:gumagatsby@266259364/aws-edge-analytics@1423275127"
}

variable "raw_retention_days" {
  description = "Raw logs contain IP addresses and are deleted after this many days (N1)."
  type        = number
  default     = 7
  validation {
    condition     = var.raw_retention_days >= 1 && var.raw_retention_days <= 30
    error_message = "Keep raw logs between 1 and 30 days."
  }
}

variable "normalise_urls" {
  description = "When true, the viewer-request function removes tracking parameters before the cache lookup."
  type        = bool
  default     = true
}

variable "price_class" {
  description = "CloudFront price class. PriceClass_All so every edge location appears in the logs."
  type        = string
  default     = "PriceClass_All"
  validation {
    condition     = contains(["PriceClass_100", "PriceClass_200", "PriceClass_All"], var.price_class)
    error_message = "Must be PriceClass_100, PriceClass_200 or PriceClass_All."
  }
}

variable "schedule_enabled" {
  description = "Run the pipeline every day at 05:00 UTC (N5)."
  type        = bool
  default     = true
}

variable "budget_limit_usd" {
  description = "Monthly budget; an alert fires at 80% and 100% (N10)."
  type        = number
  default     = 10
}
