-- Replace one day of the fact table from the clean layer.
DELETE FROM ${curated}.fact_request WHERE day = DATE '${day}';

INSERT INTO ${curated}.fact_request
SELECT request_id, day, event_ts, hour, edge_code, edge_location, country, content_group, path, device_class,
       bot_class, bot_reason, ab_group, ab_new_visitor,
       content_group = 'checkout' AND status = 200 AS is_conversion,
       status,
       coalesce(cache_behavior, '*') <> '/api/*' AS cacheable,
       result_type IN ('Hit', 'RefreshHit') AS is_cache_hit,
       result_type, bytes_sent, ttfb_s * 1000, time_taken_s * 1000, tracking_params, stripped_params,
       source, visitor_id
FROM ${clean}.requests
WHERE day = DATE '${day}';
