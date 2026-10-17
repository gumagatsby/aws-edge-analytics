data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  # Account ID in bucket names keeps them globally unique without random suffixes.
  bucket = {
    raw       = "${var.name}-raw-${local.account_id}"
    lake      = "${var.name}-lake-${local.account_id}"
    athena    = "${var.name}-athena-${local.account_id}"
    site      = "${var.name}-site-${local.account_id}"
    artifacts = "${var.name}-artifacts-${local.account_id}"
  }
  clean_db   = replace("${var.name}_clean", "-", "_")
  curated_db = replace("${var.name}_curated", "-", "_")
}
