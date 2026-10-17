terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
    time    = { source = "hashicorp/time", version = "~> 0.12" }
  }

  # Bucket and region are passed at init time: see README "Deploying".
  backend "s3" {
    key          = "edge-analytics/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

locals {
  tags = { Project = "edge-analytics", ManagedBy = "terraform" }
}

provider "aws" {
  region = var.region
  default_tags { tags = local.tags }
}

# CloudFront log delivery is configured through the CloudWatch Logs API in us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags { tags = local.tags }
}
