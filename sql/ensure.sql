-- Idempotent set-up, run at the start of every pipeline execution.
-- ${...} placeholders are filled by the pipeline function; ${day} is validated as a date first.

CREATE EXTERNAL TABLE IF NOT EXISTS ${clean}.seed_edge_locations (
  edge_code string, city string, country_code string, continent string, pricing_region string, price_class string)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
LOCATION 's3://${artifacts}/seeds/edge_locations/'
TBLPROPERTIES ('skip.header.line.count' = '1');

CREATE EXTERNAL TABLE IF NOT EXISTS ${clean}.seed_cloudfront_prices (
  pricing_region string, usd_per_gb double, description string, fetched string)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
LOCATION 's3://${artifacts}/seeds/cloudfront_prices/'
TBLPROPERTIES ('skip.header.line.count' = '1');

-- Star schema: one fact table at one row per request, and its dimensions.
CREATE TABLE IF NOT EXISTS ${curated}.fact_request (
  request_id string, day date, event_ts timestamp, hour int, edge_code string, edge_location string,
  country string, content_group string, path string, device_class string, bot_class string, bot_reason string,
  ab_group string, ab_new_visitor boolean, is_conversion boolean, status int, cacheable boolean,
  is_cache_hit boolean, result_type string, bytes_sent bigint, ttfb_ms double, time_taken_ms double,
  tracking_params int, stripped_params int, source string, visitor_id string)
PARTITIONED BY (day)
LOCATION 's3://${lake}/curated/fact_request/'
TBLPROPERTIES ('table_type' = 'ICEBERG', 'format' = 'parquet', 'write_compression' = 'zstd');

CREATE TABLE IF NOT EXISTS ${curated}.dim_edge_location (
  edge_code string, city string, country_code string, continent string, pricing_region string, price_class string)
LOCATION 's3://${lake}/curated/dim_edge_location/'
TBLPROPERTIES ('table_type' = 'ICEBERG');

CREATE TABLE IF NOT EXISTS ${curated}.dim_date (
  day date, year int, month int, day_of_month int, iso_week int, day_of_week int, day_name string, is_weekend boolean)
LOCATION 's3://${lake}/curated/dim_date/'
TBLPROPERTIES ('table_type' = 'ICEBERG');

CREATE TABLE IF NOT EXISTS ${curated}.dim_content (content_group string, description string, is_page boolean)
LOCATION 's3://${lake}/curated/dim_content/'
TBLPROPERTIES ('table_type' = 'ICEBERG');

CREATE TABLE IF NOT EXISTS ${curated}.dim_client (bot_class string, device_class string, description string)
LOCATION 's3://${lake}/curated/dim_client/'
TBLPROPERTIES ('table_type' = 'ICEBERG');

-- Report tables, one partition per day. Analysts read these; they hold no visitor identifiers.
CREATE TABLE IF NOT EXISTS ${curated}.agg_edge_daily (
  day date, source string, edge_code string, city string, country_code string, pricing_region string,
  price_class string, requests bigint, gb double, cacheable_requests bigint, cache_hits bigint,
  ttfb_hit_p50_ms double, ttfb_miss_p50_ms double, ttfb_miss_p90_ms double, errors_4xx bigint,
  errors_5xx bigint, bot_requests bigint)
PARTITIONED BY (day) LOCATION 's3://${lake}/curated/agg_edge_daily/' TBLPROPERTIES ('table_type' = 'ICEBERG');

CREATE TABLE IF NOT EXISTS ${curated}.agg_country_daily (
  day date, source string, country string, requests bigint, human_requests bigint, gb double,
  cacheable_requests bigint, cache_hits bigint, ttfb_p50_ms double, ttfb_p90_ms double)
PARTITIONED BY (day) LOCATION 's3://${lake}/curated/agg_country_daily/' TBLPROPERTIES ('table_type' = 'ICEBERG');

CREATE TABLE IF NOT EXISTS ${curated}.agg_ab_daily (
  day date, source string, ab_group string, visitors bigint, converters bigint)
PARTITIONED BY (day) LOCATION 's3://${lake}/curated/agg_ab_daily/' TBLPROPERTIES ('table_type' = 'ICEBERG');

CREATE TABLE IF NOT EXISTS ${curated}.agg_bots_daily (
  day date, source string, bot_class string, bot_reason string, requests bigint, gb double)
PARTITIONED BY (day) LOCATION 's3://${lake}/curated/agg_bots_daily/' TBLPROPERTIES ('table_type' = 'ICEBERG');

CREATE TABLE IF NOT EXISTS ${curated}.agg_errors_daily (
  day date, source string, status int, path string, edge_code string, requests bigint)
PARTITIONED BY (day) LOCATION 's3://${lake}/curated/agg_errors_daily/' TBLPROPERTIES ('table_type' = 'ICEBERG');

CREATE TABLE IF NOT EXISTS ${curated}.agg_cache_daily (
  day date, source string, content_group string, arrived_with_tracking boolean, normalised boolean,
  cacheable_requests bigint, cache_hits bigint)
PARTITIONED BY (day) LOCATION 's3://${lake}/curated/agg_cache_daily/' TBLPROPERTIES ('table_type' = 'ICEBERG');

CREATE TABLE IF NOT EXISTS ${curated}.agg_cost_daily (
  day date, source string, pricing_region string, price_class string, gb double, usd_per_gb double, usd double)
PARTITIONED BY (day) LOCATION 's3://${lake}/curated/agg_cost_daily/' TBLPROPERTIES ('table_type' = 'ICEBERG');

-- Small dimensions are rebuilt every run from seed data and fixed lists.
DELETE FROM ${curated}.dim_edge_location;

INSERT INTO ${curated}.dim_edge_location
SELECT edge_code, city, country_code, continent, pricing_region, price_class FROM ${clean}.seed_edge_locations
UNION ALL SELECT 'UNK', 'Unknown', '--', 'Unknown', 'Unknown', 'Unknown';

DELETE FROM ${curated}.dim_date;

INSERT INTO ${curated}.dim_date
SELECT d, year(d), month(d), day(d), week(d), day_of_week(d), date_format(d, '%W'), day_of_week(d) >= 6
FROM UNNEST(sequence(DATE '2026-01-01', DATE '2027-12-31', INTERVAL '1' DAY)) AS t(d);

DELETE FROM ${curated}.dim_content;

INSERT INTO ${curated}.dim_content VALUES
  ('home', 'Homepage, design A or B', true), ('product', 'Product page', true),
  ('checkout', 'Purchase (the experiment''s conversion event)', false), ('api', 'Storefront API', false),
  ('asset', 'Stylesheet, image or other static file', false), ('insights', 'This dashboard', true),
  ('other', 'Anything else, including unknown paths', false);

DELETE FROM ${curated}.dim_client;

INSERT INTO ${curated}.dim_client
SELECT b, d, b || ' on ' || d
FROM UNNEST(ARRAY['human', 'known_bot', 'suspected_bot']) AS x(b)
CROSS JOIN UNNEST(ARRAY['desktop', 'mobile', 'tablet', 'bot']) AS y(d);
