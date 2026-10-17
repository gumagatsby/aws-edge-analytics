resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.name}-site"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_origin_access_control" "api" {
  name                              = "${var.name}-api"
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# D2: CloudFront Functions run on every request at the edge.
resource "aws_cloudfront_function" "viewer_request" {
  name    = "${var.name}-viewer-request"
  runtime = "cloudfront-js-2.0"
  comment = "A/B assignment, tracking-parameter removal, log tagging"
  publish = true
  code    = templatefile("${path.module}/../edge/viewer_request.js", { normalise = var.normalise_urls })
}

resource "aws_cloudfront_function" "viewer_response" {
  name    = "${var.name}-viewer-response"
  runtime = "cloudfront-js-2.0"
  comment = "Persists a new A/B assignment in a cookie"
  publish = true
  code    = file("${path.module}/../edge/viewer_response.js")
}

# Query strings are part of the cache key, as on most real sites; tracking
# parameters therefore fragment the cache unless the edge function removes them.
resource "aws_cloudfront_cache_policy" "site" {
  name        = "${var.name}-site"
  min_ttl     = 0
  default_ttl = 3600
  max_ttl     = 86400
  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true
    cookies_config { cookie_behavior = "none" }
    headers_config { header_behavior = "none" }
    query_strings_config { query_string_behavior = "all" }
  }
}

locals {
  managed = {
    caching_disabled       = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    all_viewer_except_host = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    security_headers       = "67f7725c-6f97-4210-82d7-5512b31e9d03"
  }
  edge_functions = {
    "viewer-request"  = aws_cloudfront_function.viewer_request.arn
    "viewer-response" = aws_cloudfront_function.viewer_response.arn
  }
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "${var.name} storefront"
  price_class         = var.price_class
  default_root_object = "index.html"
  http_version        = "http2and3"
  is_ipv6_enabled     = true

  origin {
    origin_id                = "site"
    domain_name              = module.site.regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  origin {
    origin_id                = "api"
    domain_name              = replace(replace(aws_lambda_function_url.api.function_url, "https://", ""), "/", "")
    origin_access_control_id = aws_cloudfront_origin_access_control.api.id
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id           = "site"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.site.id
    response_headers_policy_id = local.managed.security_headers
    dynamic "function_association" {
      for_each = local.edge_functions
      content {
        event_type   = function_association.key
        function_arn = function_association.value
      }
    }
  }

  # The API also runs the request function, so purchases carry the visitor's A/B group.
  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = "api"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = local.managed.caching_disabled
    origin_request_policy_id   = local.managed.all_viewer_except_host
    response_headers_policy_id = local.managed.security_headers
    dynamic "function_association" {
      for_each = local.edge_functions
      content {
        event_type   = function_association.key
        function_arn = function_association.value
      }
    }
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate { cloudfront_default_certificate = true }
}
