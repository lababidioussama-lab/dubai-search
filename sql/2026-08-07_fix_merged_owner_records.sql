-- ============================================================================
-- Fix: owner records that merged several different properties into one row
-- ============================================================================
--
-- Background
-- ----------
-- Rows in public.owners are keyed by phone number (ext_key = 'p:<phone>').
-- Every import row carrying the same phone was folded into a single owner
-- row, and because each source spreadsheet names the same concept with a
-- different column header ('size' vs 'size  sqm' vs 'total area',
-- 'landnumber' vs 'land number', 'date' vs 'regis', 'nameen' vs 'name'),
-- nothing overwrote anything - the competing keys simply piled up next to
-- each other inside raw_data.
--
-- The result is a card that mixes fields from two or more real properties.
-- Owner 189817 (ABDUL AZIZ GHULAM SADDIQ) carried, in one row:
--   project             = DAMAC LAGOONS - PORTOFINO  (land 10972, 219.6 sqm, 2024-01-09)
--   location            = Jumeirah Village Triangle  (land 1737, 710.83 sqm, 2020-08-20)
--   plot registeration  = JVT04D2VS018
--   procedurevalue      = 1850000                    (the JVT price)
--   name                = Vakil Mokhamad             (a different person entirely)
--
-- That last one matters beyond display: search_records() returns
-- raw_data->>'name' in preference to 'nameen', so search results were
-- showing the wrong person's name - and sometimes a building name
-- ('Sulafa Tower', 'THE RESIDENCES AT MARINA GATE 1') - as the owner.
--
-- Strategy
-- --------
-- 1. Detect merged rows precisely: two keys that describe the *same* concept
--    holding *different* values. Land numbers, sizes, dates, property types
--    and owner names cannot legitimately disagree inside one transaction.
--    (A project-vs-location text mismatch is NOT used - that is normal
--    building-vs-community hierarchy, not corruption.)
-- 2. Resolve each merged row against public.property_index - one clean row
--    per real property - by owner identity: normalised name + a phone the
--    owner actually holds.
-- 3. Rebuild the row: keep only the person-level keys, then write the
--    property fields back from property_index so every field describes the
--    same property.
-- 4. Where the owner really does hold several properties, list them all under
--    'properties' and say which one the scalar fields describe.
-- 5. Where nothing resolves, leave the values alone but stamp 'data_conflict'
--    so the UI flags the row instead of presenting mixed fields as fact.
--
-- Every touched row is backed up first in owners_merge_fix_backup, so the
-- whole operation is reversible (see section 6).
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 0. Indexes supporting identity resolution
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_pidx_owner_norm_lower
  ON public.property_index (lower(owner_name_norm));

CREATE INDEX IF NOT EXISTS idx_pidx_contact_core
  ON public.property_index (right(regexp_replace(coalesce(contact, ''), '\D', '', 'g'), 9));


-- ---------------------------------------------------------------------------
-- 1. Helpers
-- ---------------------------------------------------------------------------

-- Placeholder junk ('null', 'none', '-', ...) is stored as literal text all
-- over this database and is what broke key-based property resolution in the
-- first place: unit_clean = 'null' is not an empty unit, so smart_search's
-- key builder treated it as a real unit number, the property_key_map lookup
-- missed, and the merged blob was served straight through.
CREATE OR REPLACE FUNCTION public.nz(t text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
  SELECT CASE
    WHEN t IS NULL THEN NULL
    WHEN lower(btrim(t)) IN ('', 'null', 'none', 'n/a', 'na', 'nan', '-', '--',
                             'undefined', '(null)', 'nil') THEN NULL
    ELSE btrim(t)
  END
$$;

-- Names differ across sheets by spacing far too often to treat that as
-- evidence of a merge ('BASHAR  FARHAT' vs 'BASHAR FARHAT').
CREATE OR REPLACE FUNCTION public.name_key_norm(t text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
  SELECT lower(regexp_replace(coalesce(public.nz(t), ''), '\s+', ' ', 'g'))
$$;

-- Name keys holding somebody *other* than this record's owner. 'nameen' is
-- the DLD-sourced owner name and agrees with owners.full_name; 'name' and
-- 'owner name' come from other sheets and, in a merged row, carry the
-- counterparty of an unrelated transaction (or a building name).
CREATE OR REPLACE FUNCTION public.foreign_name_keys(r jsonb)
RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
  SELECT coalesce(array_agg(k), ARRAY[]::text[])
  FROM unnest(ARRAY['name', 'owner name']) k
  WHERE public.nz(r->>'nameen') IS NOT NULL
    AND public.nz(r->>k) IS NOT NULL
    AND public.name_key_norm(r->>k) <> public.name_key_norm(r->>'nameen')
$$;

-- Keys that describe the *person*, which property_index cannot supply and
-- which must survive the rebuild. Everything else in a resolved row is
-- property/transaction data and gets replaced wholesale from property_index.
--
-- This is an allowlist on purpose. The first attempt used a blocklist of
-- known property keys and still leaked: 'plot registeration' (holding the
-- other property's plot code) and 'transaction value  aed' (holding the other
-- property's price) both survived it. The source spreadsheets spell the same
-- field in ways no blocklist can anticipate, and one missed spelling is
-- exactly how another property's values get back into the card.
CREATE OR REPLACE FUNCTION public.person_keys_only(r jsonb)
RETURNS jsonb
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
  SELECT coalesce(jsonb_object_agg(e.k, e.v), '{}'::jsonb)
  FROM jsonb_each(coalesce(r, '{}'::jsonb)) AS e(k, v)
  WHERE lower(e.k) = 'nameen'
     OR lower(e.k) ~ '(phone|mobile|whatsapp|telephone|email|e-mail|nationality|country|passport|birth|gender|unifiednumber|unified number|uae ?id|idnumber|id ?number)'
$$;

-- True when raw_data provably describes more than one property/person.
-- Each clause compares two keys that mean the same thing; inside a single
-- genuine transaction they cannot disagree.
--
-- The size comparison must sit inside a CASE: SQL does not guarantee
-- left-to-right AND evaluation, so a regex guard in the same AND chain does
-- not stop the planner from evaluating the ::numeric cast first, and values
-- like the literal string 'NULL' then raise 22P02.
CREATE OR REPLACE FUNCTION public.raw_is_merged(r jsonb)
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
  SELECT coalesce(CASE WHEN r IS NULL THEN false ELSE (
       -- two different people's names in one row
       (public.nz(r->>'nameen') IS NOT NULL AND public.nz(r->>'name') IS NOT NULL
        AND public.name_key_norm(r->>'nameen') <> public.name_key_norm(r->>'name'))
       -- two different land numbers
    OR (public.nz(r->>'landnumber') IS NOT NULL AND public.nz(r->>'land number') IS NOT NULL
        AND lower(public.nz(r->>'landnumber')) <> lower(public.nz(r->>'land number')))
       -- two different sizes
    OR (CASE WHEN public.nz(r->>'size') ~ '^[0-9]+(\.[0-9]+)?$'
              AND public.nz(r->>'size  sqm') ~ '^[0-9]+(\.[0-9]+)?$'
             THEN public.nz(r->>'size')::numeric <> public.nz(r->>'size  sqm')::numeric
             ELSE false END)
       -- two different property types
    OR (public.nz(r->>'propertytypeen') IS NOT NULL AND public.nz(r->>'property type') IS NOT NULL
        AND lower(public.nz(r->>'propertytypeen')) <> lower(public.nz(r->>'property type')))
       -- two different registration dates
    OR (public.nz(r->>'date') ~ '^\d{4}-\d{2}-\d{2}$'
        AND public.nz(r->>'regis') ~ '^\d{4}-\d{2}-\d{2}'
        AND public.nz(r->>'date') <> left(public.nz(r->>'regis'), 10))
  ) END, false)
$$;


-- ---------------------------------------------------------------------------
-- 2. Backup + progress tracking
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.owners_merge_fix_backup (
  owner_id               bigint PRIMARY KEY,
  raw_data_before        jsonb,
  project_name_before    text,
  building_before        text,
  unit_before            text,
  unit_clean_before      text,
  community_clean_before text,
  resolution             text,
  fixed_at               timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.merge_fix_state (
  id                     int PRIMARY KEY DEFAULT 1,
  cursor_id              bigint NOT NULL DEFAULT 0,
  placeholder_cursor_id  bigint NOT NULL DEFAULT 0,
  updated_at             timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT merge_fix_state_single_row CHECK (id = 1)
);

INSERT INTO public.merge_fix_state (id, cursor_id)
VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;


-- ---------------------------------------------------------------------------
-- 3. The repair
-- ---------------------------------------------------------------------------
--
-- Walks public.owners in id order. Stops after p_seconds of wall clock so it
-- can be driven from a timeout-bound client by calling it until done = true.
-- Naturally idempotent: a repaired row no longer satisfies raw_is_merged().
--
CREATE OR REPLACE FUNCTION public.fix_merged_owner_batch(
  p_seconds     integer DEFAULT 40,
  p_id_span     integer DEFAULT 50000,
  p_max_batches integer DEFAULT NULL
)
RETURNS TABLE(scanned bigint, resolved bigint, flagged bigint, cursor_at bigint, done boolean)
LANGUAGE plpgsql
AS $fn$
DECLARE
  v_started   timestamptz := clock_timestamp();
  v_cursor    bigint;
  v_max_id    bigint;
  v_lo        bigint;
  v_hi        bigint;
  v_resolved  bigint := 0;
  v_flagged   bigint := 0;
  v_scanned   bigint := 0;
  v_batches   integer := 0;
  v_n         bigint;
BEGIN
  SELECT s.cursor_id INTO v_cursor FROM public.merge_fix_state s WHERE s.id = 1 FOR UPDATE;
  SELECT max(o.id) INTO v_max_id FROM public.owners o;

  LOOP
    EXIT WHEN v_cursor >= v_max_id;
    EXIT WHEN clock_timestamp() - v_started > make_interval(secs => p_seconds);
    EXIT WHEN p_max_batches IS NOT NULL AND v_batches >= p_max_batches;

    v_batches := v_batches + 1;
    v_lo := v_cursor;
    v_hi := v_cursor + p_id_span;

    CREATE TEMP TABLE _batch ON COMMIT DROP AS
      SELECT o.id, o.raw_data, o.name_norm
      FROM public.owners o
      WHERE o.id > v_lo AND o.id <= v_hi
        AND public.raw_is_merged(o.raw_data);

    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_scanned := v_scanned + v_n;

    -- Candidate properties per merged row, matched on owner identity.
    -- property_index can hold the same physical property more than once (one
    -- row per source file), so collapse on a property identity first -
    -- otherwise one property counts as several and the row is wrongly
    -- reported as a multi-property owner.
    CREATE TEMP TABLE _cand ON COMMIT DROP AS
      WITH matches AS (
        SELECT b.id AS owner_id,
               pi.*,
               lower(coalesce(public.nz(pi.cluster), public.nz(pi.master_project),
                              public.nz(pi.project), '')
                     || '|' ||
                     coalesce(public.nz(pi.land_number), public.nz(pi.reg_no),
                              public.nz(pi.unit_number), public.nz(pi.building_no), '')
               ) AS prop_key
        FROM _batch b
        JOIN LATERAL (
          SELECT array_agg(ph.phone_core) AS cores
          FROM public.phones ph WHERE ph.owner_id = b.id
        ) pc ON pc.cores IS NOT NULL
        JOIN public.property_index pi
          ON lower(pi.owner_name_norm) = b.name_norm
         AND right(regexp_replace(coalesce(pi.contact, ''), '\D', '', 'g'), 9) = ANY(pc.cores)
      ),
      dedup AS (
        SELECT DISTINCT ON (owner_id, prop_key) *
        FROM matches
        ORDER BY owner_id, prop_key, last_reg_date DESC NULLS LAST,
                 tx_count DESC NULLS LAST, id DESC
      )
      SELECT owner_id,
             id AS pidx_id,
             project, master_project, cluster, building_name, building_no,
             unit_number, property_number, reg_no, land_number, size_sqm,
             plot_size, built_up, beds, property_type, sub_type, usage,
             completion_status, last_reg_date, last_amount, procedure_name,
             party_type, source_file, tx_count,
             row_number() OVER (PARTITION BY owner_id
                                ORDER BY last_reg_date DESC NULLS LAST,
                                         tx_count DESC NULLS LAST, id DESC) AS rn,
             count(*)     OVER (PARTITION BY owner_id) AS n_props
      FROM dedup;

    -- Back up before touching anything.
    INSERT INTO public.owners_merge_fix_backup (
      owner_id, raw_data_before, project_name_before, building_before,
      unit_before, unit_clean_before, community_clean_before, resolution)
    SELECT o.id, o.raw_data, o.project_name, o.building, o.unit, o.unit_clean,
           o.community_clean,
           CASE WHEN c.owner_id IS NULL THEN 'flagged_unresolved'
                WHEN c.n_props > 1     THEN 'resolved_multi'
                ELSE 'resolved_single' END
    FROM _batch b
    JOIN public.owners o ON o.id = b.id
    LEFT JOIN _cand c ON c.owner_id = b.id AND c.rn = 1
    ON CONFLICT (owner_id) DO NOTHING;

    -- (a) Rows that resolved: rebuild the property fields from property_index.
    WITH plist AS (
      SELECT c.owner_id,
             jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
               'community',   coalesce(c.cluster, c.master_project),
               'project',     c.project,
               'plot / unit', coalesce(public.nz(c.unit_number), public.nz(c.reg_no),
                                       public.nz(c.building_no), public.nz(c.land_number)),
               'size sqm',    c.size_sqm::text,
               'type',        c.property_type,
               'price aed',   c.last_amount::text,
               'date',        c.last_reg_date::text,
               'role',        c.party_type))
               ORDER BY c.last_reg_date DESC NULLS LAST) AS props
      FROM _cand c
      GROUP BY c.owner_id
    ),
    pick AS (
      SELECT c.*, p.props
      FROM _cand c JOIN plist p ON p.owner_id = c.owner_id
      WHERE c.rn = 1
    )
    UPDATE public.owners o
    SET raw_data = (
          public.person_keys_only(o.raw_data)
          || jsonb_strip_nulls(jsonb_build_object(
               'project',                       pick.project,
               'master project',                pick.master_project,
               'location',                      coalesce(pick.master_project, pick.cluster),
               'community',                     pick.cluster,
               'buildingnameen',                pick.building_name,
               'building no',                   pick.building_no,
               'unitnumber',                    pick.unit_number,
               'unit',                          pick.unit_number,
               'property number',               pick.property_number,
               'landnumber',                    pick.land_number,
               'land number',                   pick.land_number,
               'plot number',                   pick.land_number,
               'plot pre reg no',               pick.reg_no,
               'size',                          pick.size_sqm::text,
               'plot size',                     pick.plot_size::text,
               'built up',                      pick.built_up::text,
               'beds',                          pick.beds,
               'propertytypeen',                pick.property_type,
               'property type',                 pick.property_type,
               'sub type',                      pick.sub_type,
               'usage',                         pick.usage,
               'completion status',             pick.completion_status,
               'regis',                         pick.last_reg_date::text,
               'date',                          pick.last_reg_date::text,
               'procedurevalue',                pick.last_amount::text,
               'procedurenameen',               pick.procedure_name,
               'procedurepartytypenameen',      pick.party_type,
               'client type',                   pick.party_type,
               'source file',                   pick.source_file,
               'transactions on this property', pick.tx_count::text,
               'detail_source',                 'property_index (resolved by owner name + phone)'))
          || CASE WHEN pick.n_props > 1 THEN jsonb_build_object(
                 'properties',       pick.props,
                 'properties_count', pick.n_props,
                 'data_conflict',
                 'this owner record had fields from ' || pick.n_props ||
                 ' different properties merged into one row; the fields above now' ||
                 ' describe the most recent one only - see "properties" for the full list')
               ELSE '{}'::jsonb END
        ),
        project_name    = coalesce(public.nz(pick.project), public.nz(pick.master_project),
                                   public.nz(pick.cluster), o.project_name),
        community_clean = coalesce(public.nz(pick.cluster), public.nz(pick.master_project),
                                   public.nz(pick.project), o.community_clean),
        building        = coalesce(public.nz(pick.building_name), public.nz(pick.project), o.building),
        unit            = coalesce(public.nz(pick.unit_number), public.nz(pick.reg_no),
                                   public.nz(pick.building_no), public.nz(pick.land_number),
                                   public.nz(o.unit)),
        unit_clean      = coalesce(public.nz(pick.unit_number), public.nz(pick.reg_no),
                                   public.nz(pick.building_no), public.nz(pick.land_number),
                                   public.nz(o.unit_clean)),
        updated_at      = now()
    FROM pick
    WHERE o.id = pick.owner_id;

    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_resolved := v_resolved + v_n;

    -- (b) Rows with no match in property_index: we cannot say which value is
    --     right, so keep them and flag them. The one thing we can fix safely
    --     is a foreign person name, which search_records() displays in
    --     preference to 'nameen'.
    UPDATE public.owners o
    SET raw_data = (o.raw_data - public.foreign_name_keys(o.raw_data))
          || jsonb_build_object('data_conflict',
               'this record mixes fields from more than one property; no matching' ||
               ' property record was found, so individual fields below may belong' ||
               ' to different properties - verify before treating any of them as fact'),
        updated_at = now()
    FROM _batch b
    WHERE o.id = b.id
      AND NOT EXISTS (SELECT 1 FROM _cand c WHERE c.owner_id = b.id);

    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_flagged := v_flagged + v_n;

    DROP TABLE _batch;
    DROP TABLE _cand;

    v_cursor := v_hi;
  END LOOP;

  UPDATE public.merge_fix_state s
  SET cursor_id = v_cursor, updated_at = now()
  WHERE s.id = 1;

  RETURN QUERY SELECT v_scanned, v_resolved, v_flagged, v_cursor, (v_cursor >= v_max_id);
END;
$fn$;


-- ---------------------------------------------------------------------------
-- 4. Placeholder cleanup on the owner columns
-- ---------------------------------------------------------------------------
--
-- Normalising unit / unit_clean / building lets smart_search's key builder
-- fall through to the plot / land number instead of trying to look up the
-- literal string 'null', which is what left these rows unresolved.
--
CREATE OR REPLACE FUNCTION public.fix_placeholder_owner_cols(
  p_seconds  integer DEFAULT 40,
  p_id_span  integer DEFAULT 200000
)
RETURNS TABLE(cleaned bigint, cursor_at bigint, done boolean)
LANGUAGE plpgsql
AS $fn$
DECLARE
  v_started timestamptz := clock_timestamp();
  v_cursor  bigint;
  v_max_id  bigint;
  v_hi      bigint;
  v_total   bigint := 0;
  v_n       bigint;
BEGIN
  SELECT s.placeholder_cursor_id INTO v_cursor
  FROM public.merge_fix_state s WHERE s.id = 1 FOR UPDATE;
  v_cursor := coalesce(v_cursor, 0);

  SELECT max(o.id) INTO v_max_id FROM public.owners o;

  LOOP
    EXIT WHEN v_cursor >= v_max_id;
    EXIT WHEN clock_timestamp() - v_started > make_interval(secs => p_seconds);

    v_hi := v_cursor + p_id_span;

    UPDATE public.owners o
    SET unit       = public.nz(o.unit),
        unit_clean = public.nz(o.unit_clean),
        building   = public.nz(o.building)
    WHERE o.id > v_cursor AND o.id <= v_hi
      AND (o.unit       IS DISTINCT FROM public.nz(o.unit)
        OR o.unit_clean IS DISTINCT FROM public.nz(o.unit_clean)
        OR o.building   IS DISTINCT FROM public.nz(o.building));

    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_total := v_total + v_n;
    v_cursor := v_hi;
  END LOOP;

  UPDATE public.merge_fix_state s
  SET placeholder_cursor_id = v_cursor, updated_at = now()
  WHERE s.id = 1;

  RETURN QUERY SELECT v_total, v_cursor, (v_cursor >= v_max_id);
END;
$fn$;


-- ---------------------------------------------------------------------------
-- 5. Driving it to completion
-- ---------------------------------------------------------------------------
--
-- One pg_cron tick: repair merged rows first, then the placeholder cleanup,
-- then retire the job. The advisory lock stops a slow tick from overlapping
-- the next one (pg_cron does not serialise runs by itself).
--
-- Paced deliberately: this instance is small (shared_buffers 256MB) and
-- Postgres restarted once during the first run.
--
-- Keep the placeholder span small. It fires owners_sync_search once per
-- updated row, which rebuilds that row's search blob from raw_data, so a
-- 200k-id span exceeded the 2-minute statement timeout. Both passes run in
-- one transaction, so that rollback also reverted the merge pass's progress,
-- and the job re-scanned the same final chunk every tick until the span
-- shrank. 10k-id spans commit comfortably; the loop still does many spans
-- per tick, so throughput is unaffected.
--
CREATE OR REPLACE FUNCTION public.merge_fix_cron_tick()
RETURNS void
LANGUAGE plpgsql
AS $fn$
DECLARE
  r1 record;
  r2 record;
BEGIN
  IF NOT pg_try_advisory_lock(918273645) THEN
    RETURN;
  END IF;

  SELECT * INTO r1 FROM public.fix_merged_owner_batch(20, 25000);

  IF r1.done THEN
    SELECT * INTO r2 FROM public.fix_placeholder_owner_cols(15, 10000);
    IF r2.done THEN
      BEGIN
        PERFORM cron.unschedule('merge_fix_job');
      EXCEPTION WHEN OTHERS THEN
        NULL;
      END;
    END IF;
  END IF;

  PERFORM pg_advisory_unlock(918273645);
END;
$fn$;

-- Start it (the job unschedules itself when both passes report done):
--   SELECT cron.schedule('merge_fix_job', '*/2 * * * *',
--                        $$select public.merge_fix_cron_tick()$$);
--
-- Watch progress:
--   SELECT * FROM public.merge_fix_state;
--   SELECT resolution, count(*) FROM public.owners_merge_fix_backup
--   GROUP BY resolution;


-- ---------------------------------------------------------------------------
-- 6. Rollback (kept alongside the fix so it is never lost)
-- ---------------------------------------------------------------------------
--
--   SELECT cron.unschedule('merge_fix_job');
--
--   UPDATE public.owners o
--   SET raw_data        = b.raw_data_before,
--       project_name    = b.project_name_before,
--       building        = b.building_before,
--       unit            = b.unit_before,
--       unit_clean      = b.unit_clean_before,
--       community_clean = b.community_clean_before
--   FROM public.owners_merge_fix_backup b
--   WHERE o.id = b.owner_id;
--
-- ---------------------------------------------------------------------------
