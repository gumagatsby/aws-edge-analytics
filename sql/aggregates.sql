-- Rebuild one day of every report table from the fact table.
-- Percentiles are exact (nearest rank: the value at position ceil(p x n) in sorted order).
-- approx_percentile can differ between runs, and a re-run must give identical tables (N4).
DELETE FROM ${curated}.agg_edge_daily WHERE day = DATE '${day}';

INSERT INTO ${curated}.agg_edge_daily
SELECT f.day, f.source, f.edge_code, coalesce(e.city, 'Unknown'), coalesce(e.country_code, '--'),
       coalesce(e.pricing_region, 'Unknown'), coalesce(e.price_class, 'Unknown'),
       count(*), sum(f.bytes_sent) / 1e9,
       count_if(f.cacheable), count_if(f.cacheable AND f.is_cache_hit),
       element_at(array_sort(array_agg(f.ttfb_ms) FILTER (WHERE f.ttfb_ms IS NOT NULL AND f.is_cache_hit)),
                  greatest(1, CAST(ceil(0.5 * count_if(f.ttfb_ms IS NOT NULL AND f.is_cache_hit)) AS integer))),
       element_at(array_sort(array_agg(f.ttfb_ms) FILTER (WHERE f.ttfb_ms IS NOT NULL AND NOT f.is_cache_hit AND f.status < 400)),
                  greatest(1, CAST(ceil(0.5 * count_if(f.ttfb_ms IS NOT NULL AND NOT f.is_cache_hit AND f.status < 400)) AS integer))),
       element_at(array_sort(array_agg(f.ttfb_ms) FILTER (WHERE f.ttfb_ms IS NOT NULL AND NOT f.is_cache_hit AND f.status < 400)),
                  greatest(1, CAST(ceil(0.9 * count_if(f.ttfb_ms IS NOT NULL AND NOT f.is_cache_hit AND f.status < 400)) AS integer))),
       count_if(f.status BETWEEN 400 AND 499), count_if(f.status >= 500), count_if(f.bot_class <> 'human')
FROM ${curated}.fact_request f
LEFT JOIN ${curated}.dim_edge_location e ON e.edge_code = f.edge_code
WHERE f.day = DATE '${day}'
GROUP BY 1, 2, 3, 4, 5, 6, 7;

DELETE FROM ${curated}.agg_country_daily WHERE day = DATE '${day}';

INSERT INTO ${curated}.agg_country_daily
SELECT day, source, coalesce(country, '--'), count(*), count_if(bot_class = 'human'), sum(bytes_sent) / 1e9,
       count_if(cacheable), count_if(cacheable AND is_cache_hit),
       element_at(array_sort(array_agg(ttfb_ms) FILTER (WHERE ttfb_ms IS NOT NULL)),
                  greatest(1, CAST(ceil(0.5 * count_if(ttfb_ms IS NOT NULL)) AS integer))),
       element_at(array_sort(array_agg(ttfb_ms) FILTER (WHERE ttfb_ms IS NOT NULL)),
                  greatest(1, CAST(ceil(0.9 * count_if(ttfb_ms IS NOT NULL)) AS integer)))
FROM ${curated}.fact_request
WHERE day = DATE '${day}'
GROUP BY 1, 2, 3;

-- A visitor is a human who reached a homepage design; a converter is one of them who bought.
DELETE FROM ${curated}.agg_ab_daily WHERE day = DATE '${day}';

INSERT INTO ${curated}.agg_ab_daily
WITH seen AS (
  SELECT source, visitor_id, max_by(ab_group, event_ts) AS ab_group, bool_or(is_conversion) AS converted,
         bool_or(content_group = 'home') AS saw_home
  FROM ${curated}.fact_request
  WHERE day = DATE '${day}' AND bot_class = 'human' AND ab_group IS NOT NULL
  GROUP BY 1, 2)
SELECT DATE '${day}', source, ab_group, count(*), count_if(converted)
FROM seen WHERE saw_home
GROUP BY 1, 2, 3;

DELETE FROM ${curated}.agg_bots_daily WHERE day = DATE '${day}';

INSERT INTO ${curated}.agg_bots_daily
SELECT day, source, bot_class, coalesce(bot_reason, 'none'), count(*), sum(bytes_sent) / 1e9
FROM ${curated}.fact_request
WHERE day = DATE '${day}'
GROUP BY 1, 2, 3, 4;

DELETE FROM ${curated}.agg_errors_daily WHERE day = DATE '${day}';

INSERT INTO ${curated}.agg_errors_daily
SELECT day, source, status, path, edge_code, count(*)
FROM ${curated}.fact_request
WHERE day = DATE '${day}' AND status >= 400
GROUP BY 1, 2, 3, 4, 5;

DELETE FROM ${curated}.agg_cache_daily WHERE day = DATE '${day}';

INSERT INTO ${curated}.agg_cache_daily
SELECT day, source, content_group, tracking_params > 0 OR stripped_params > 0, stripped_params > 0,
       count(*), count_if(is_cache_hit)
FROM ${curated}.fact_request
WHERE day = DATE '${day}' AND cacheable AND bot_class = 'human'
GROUP BY 1, 2, 3, 4, 5;

DELETE FROM ${curated}.agg_cost_daily WHERE day = DATE '${day}';

-- Whole bytes are totalled first, so the result does not depend on the order in which
-- decimal values are added (a re-run must give identical tables, N4). One price per region.
INSERT INTO ${curated}.agg_cost_daily
WITH by_region AS (
  SELECT f.day, f.source, coalesce(e.pricing_region, 'Unknown') AS pricing_region,
         coalesce(e.price_class, 'Unknown') AS price_class, sum(f.bytes_sent) AS bytes_sent
  FROM ${curated}.fact_request f
  LEFT JOIN ${curated}.dim_edge_location e ON e.edge_code = f.edge_code
  WHERE f.day = DATE '${day}'
  GROUP BY 1, 2, 3, 4)
SELECT r.day, r.source, r.pricing_region, r.price_class, r.bytes_sent / 1e9, p.usd_per_gb, r.bytes_sent / 1e9 * p.usd_per_gb
FROM by_region r
LEFT JOIN ${clean}.seed_cloudfront_prices p ON p.pricing_region = r.pricing_region;
