"""The access-log fields, in the order CloudFront writes them."""

# Must match local.log_fields in terraform/logging.tf: the delivery writes them in this order.
FIELDS = [
    "date", "time", "timestamp(ms)", "x-edge-location", "sc-bytes", "c-ip", "cs-method", "cs(Host)",
    "cs-uri-stem", "sc-status", "cs(Referer)", "cs(User-Agent)", "cs-uri-query", "cs(Cookie)",
    "x-edge-result-type", "x-edge-request-id", "x-host-header", "cs-protocol", "cs-bytes", "time-taken",
    "x-forwarded-for", "ssl-protocol", "ssl-cipher", "x-edge-response-result-type", "cs-protocol-version",
    "time-to-first-byte", "x-edge-detailed-result-type", "sc-content-type", "sc-content-len", "c-country",
    "asn", "cache-behavior-path-pattern", "viewer-request-log-data",
]
