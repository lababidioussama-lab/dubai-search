-- ============================================================================
-- Fix: search_records() displayed the wrong person's name
-- ============================================================================
--
-- The name column was built as:
--
--   coalesce(NULLIF(raw_data->>'name',''), NULLIF(raw_data->>'nameen',''),
--            NULLIF(full_name,''), 'Unknown')
--
-- 'name' first. In rows that merged several source sheets (see
-- 2026-08-07_fix_merged_owner_records.sql) that key carries the counterparty
-- of an unrelated transaction, or not a person at all:
--
--   owner 20613  full_name 'ABDELHAMID MAHMOUD ABDELFATTAH MOHAMED'
--                raw_data->>'name' = 'Abdellatif Ferraq'      <- displayed
--   owner 130    full_name 'SHAHRYAR DILAWEEZ ALTAF AHMED AHMED'
--                raw_data->>'name' = 'Sparkle Tower 2'        <- displayed
--   owner 226    full_name 'MATHIEU PIERRE PASCAL LAUGA'
--                raw_data->>'name' = 'THE RESIDENCES AT MARINA GATE 1'
--
-- The data repair strips a foreign 'name' wherever it can, but that only
-- fixes rows already loaded: a future import re-introduces the same problem.
-- This makes the reader itself safe.
--
-- 'nameen' is the DLD-sourced owner name and agrees with owners.full_name, so
-- it leads, with full_name behind it. 'name' is kept as a last resort for
-- rows carrying no other name at all, rather than dropped outright.
--
-- The previous definition is saved in public.db_function_backup
-- (func_name = 'search_records') - to roll back:
--
--   SELECT definition FROM public.db_function_backup
--   WHERE func_name = 'search_records' ORDER BY backed_up_at DESC LIMIT 1;
--   -- then execute that definition
--
-- Only the name expression changes; every other column is byte-for-byte the
-- original.
-- ============================================================================

CREATE OR REPLACE FUNCTION public.search_records(
  q text DEFAULT NULL::text,
  f_community text DEFAULT NULL::text,
  f_plot text DEFAULT NULL::text,
  f_nationality text DEFAULT NULL::text,
  f_phone text DEFAULT NULL::text,
  f_size_min numeric DEFAULT NULL::numeric,
  f_size_max numeric DEFAULT NULL::numeric,
  limit_n integer DEFAULT 100)
 RETURNS TABLE(id bigint, name text, nationality text, area text, community text,
               size_sqm numeric, purchase_date text, unit_no text, plot_no text,
               price numeric, phones jsonb)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
  WITH p AS (
    SELECT
      lower(NULLIF(btrim(q),''))             AS q,
      lower(NULLIF(btrim(f_community),''))   AS f_community,
      lower(NULLIF(btrim(f_plot),''))        AS f_plot,
      lower(NULLIF(btrim(f_nationality),'')) AS f_nationality,
      NULLIF(regexp_replace(coalesce(f_phone,''), '\D', '', 'g'), '') AS f_phone,
      f_size_min AS smin,
      f_size_max AS smax,
      GREATEST(1, LEAST(coalesce(limit_n,100), 200)) AS lim
  ),
  term AS (
    SELECT coalesce(q, f_community, f_plot, f_nationality) AS t, * FROM p
  ),
  phone_ids AS (
    SELECT DISTINCT ph.owner_id
    FROM public.phones ph, p
    WHERE p.f_phone IS NOT NULL
      AND (ph.phone_core LIKE p.f_phone || '%' OR ph.phone_digits LIKE '%' || p.f_phone)
  ),
  matched AS (
    SELECT o.id, o.raw_data, o.full_name, o.project_name, o.unit
    FROM public.owners o, term t
    WHERE (t.t IS NOT NULL OR t.f_phone IS NOT NULL)
      AND (t.t IS NULL OR public.owner_search_text(o.raw_data) LIKE '%' || t.t || '%')
      AND (t.f_community IS NULL OR lower(concat_ws(' ',
            o.raw_data->>'master project', o.raw_data->>'sublocation',
            o.raw_data->>'project', o.raw_data->>'location',
            o.raw_data->>'buildingnameen')) LIKE '%' || t.f_community || '%')
      AND (t.f_plot IS NULL OR lower(concat_ws(' ',
            o.raw_data->>'plot pre reg no', o.raw_data->>'unitnumber',
            o.raw_data->>'unit', o.raw_data->>'property number',
            o.raw_data->>'landnumber')) LIKE '%' || t.f_plot || '%')
      AND (t.f_nationality IS NULL OR lower(coalesce(o.raw_data->>'countrynameen','')) LIKE '%' || t.f_nationality || '%')
      AND (t.f_phone IS NULL OR o.id IN (SELECT owner_id FROM phone_ids))
      AND (t.smin IS NULL OR (o.raw_data->>'size' ~ '^[0-9]+(\.[0-9]+)?$' AND (o.raw_data->>'size')::numeric >= t.smin))
      AND (t.smax IS NULL OR (o.raw_data->>'size' ~ '^[0-9]+(\.[0-9]+)?$' AND (o.raw_data->>'size')::numeric <= t.smax))
    LIMIT (SELECT lim FROM p)
  )
  SELECT
    m.id,
    -- CHANGED: 'nameen' / full_name lead; 'name' demoted to last resort.
    coalesce(NULLIF(m.raw_data->>'nameen',''), NULLIF(m.full_name,''),
             NULLIF(m.raw_data->>'name',''), 'Unknown') AS name,
    NULLIF(m.raw_data->>'countrynameen','') AS nationality,
    coalesce(NULLIF(m.raw_data->>'master project',''), NULLIF(m.raw_data->>'master location',''),
             NULLIF(m.raw_data->>'location',''), NULLIF(m.project_name,'')) AS area,
    coalesce(NULLIF(m.raw_data->>'sublocation',''), NULLIF(m.raw_data->>'project',''),
             NULLIF(m.raw_data->>'buildingnameen','')) AS community,
    CASE WHEN m.raw_data->>'size' ~ '^[0-9]+(\.[0-9]+)?$' THEN (m.raw_data->>'size')::numeric END AS size_sqm,
    CASE
      WHEN m.raw_data->>'date' ~ '^[0-9]{4,6}$'
        THEN to_char(DATE '1899-12-30' + (m.raw_data->>'date')::int, 'YYYY-MM-DD')
      WHEN NULLIF(m.raw_data->>'date','') IS NOT NULL
        THEN left(m.raw_data->>'date', 10)
    END AS purchase_date,
    coalesce(NULLIF(m.raw_data->>'unitnumber',''), NULLIF(m.raw_data->>'unit',''),
             NULLIF(m.raw_data->>'property number',''), NULLIF(m.unit,'')) AS unit_no,
    coalesce(NULLIF(m.raw_data->>'plot pre reg no',''), NULLIF(m.raw_data->>'landnumber','')) AS plot_no,
    CASE WHEN coalesce(m.raw_data->>'procedurevalue', m.raw_data->>'transaction amount') ~ '^[0-9]+(\.[0-9]+)?$'
      THEN coalesce(m.raw_data->>'procedurevalue', m.raw_data->>'transaction amount')::numeric END AS price,
    coalesce((
      SELECT jsonb_agg(jsonb_build_object('raw', ph.phone_raw, 'digits', ph.phone_digits, 'wa', ph.is_whatsapp)
                       ORDER BY ph.is_whatsapp DESC, ph.id)
      FROM public.phones ph WHERE ph.owner_id = m.id
    ), '[]'::jsonb) AS phones
  FROM matched m;
$function$;
