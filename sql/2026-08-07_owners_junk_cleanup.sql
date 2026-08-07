-- ============================================================================
-- Cleanup: three classes of junk in public.owners
-- ============================================================================
--
-- Separate from 2026-08-07_fix_merged_owner_records.sql. That one fixed rows
-- whose fields came from several properties; these are rows that are not
-- owner records at all, or are mislabelled.
--
-- A note on method: patterns were NOT used to find these. A first attempt at
-- a junk-name regex flagged 'SHEETAL GUPTA' (matched '^sheet'), and a broader
-- "4+ lowercase words is not a name" rule flagged real companies -
-- 'sun delta general trading llc', 'green point home real estate development
-- l.l.c'. Any regex sweep over full_name deletes real owners. Each fix below
-- is therefore scoped to a verified, enumerated set.
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 0. Backup / quarantine
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.owners_cleanup_backup (
  owner_id               bigint PRIMARY KEY,
  fix_type               text NOT NULL,
  full_name_before       text,
  project_name_before    text,
  building_before        text,
  community_clean_before text,
  fixed_at               timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.owners_quarantine (
  LIKE public.owners INCLUDING DEFAULTS
);

ALTER TABLE public.owners_quarantine
  ADD COLUMN IF NOT EXISTS quarantined_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS quarantine_reason text;


-- ---------------------------------------------------------------------------
-- 1. Sheet names sitting in project_name  (7,122 rows)
-- ---------------------------------------------------------------------------
--
-- project_name held the Excel tab name ('All_Buyers' / 'All_Sellers') while
-- the real project sat in `building`:
--
--   Hitesh Lalji Velani | project_name All_Buyers | building DAMAC LAGOONS - NICE 1
--
-- These are real people with real phones (1,576 of them have one), but
-- smart_search() explicitly drops project_name IN ('All_Buyers','All_Sellers')
-- as junk - so all 7,122 were being suppressed from search results.
--
-- 6,964 of 7,122 (97.8%) carry the real project in `building`. community_clean
-- is derived by taking the part before ' - ', which turns
-- 'DAMAC LAGOONS - NICE 1' into community 'DAMAC LAGOONS'. `building` itself
-- is left alone - it is a reasonable label and nothing depends on clearing it.

INSERT INTO public.owners_cleanup_backup
  (owner_id, fix_type, full_name_before, project_name_before, building_before, community_clean_before)
SELECT o.id, 'sheet_name_in_project', o.full_name, o.project_name, o.building, o.community_clean
FROM public.owners o
WHERE o.project_name IN ('All_Buyers','All_Sellers')
ON CONFLICT (owner_id) DO NOTHING;

UPDATE public.owners o
SET project_name    = public.nz(o.building),
    community_clean = coalesce(public.nz(o.community_clean),
                               public.nz(btrim(split_part(o.building, ' - ', 1)))),
    updated_at      = now()
WHERE o.project_name IN ('All_Buyers','All_Sellers');


-- ---------------------------------------------------------------------------
-- 2. Owners literally named 'null'  (867 rows)
-- ---------------------------------------------------------------------------
--
-- full_name held the four-character string 'null'. None has a phone, none has
-- a 'nameen' or 'name' in raw_data - but 866 of the 867 have a real unit, so
-- they are property records with no owner attached, displaying as a person
-- called "null".
--
-- Set to NULL rather than a placeholder string: readers already substitute at
-- display time (property_lookup_exact uses coalesce(owner_name, 'NO OWNER ON
-- RECORD')), and 867 rows sharing one literal name would form a fake owner in
-- owner_name_stats and in every name-based dedup key.

INSERT INTO public.owners_cleanup_backup
  (owner_id, fix_type, full_name_before, project_name_before, building_before, community_clean_before)
SELECT o.id, 'name_literal_null', o.full_name, o.project_name, o.building, o.community_clean
FROM public.owners o
WHERE lower(btrim(o.full_name)) = 'null'
ON CONFLICT (owner_id) DO NOTHING;

UPDATE public.owners o
SET full_name = NULL, updated_at = now()
WHERE lower(btrim(o.full_name)) = 'null';


-- ---------------------------------------------------------------------------
-- 3. A README sheet imported as owner rows  (55 rows)
-- ---------------------------------------------------------------------------
--
-- One contiguous block, ids 385926-385980, project 'DAMAC Lagoons
-- Consolidated', none with a phone. Every row is a line of prose from a
-- workbook summary:
--
--   'Total transaction records (deduplicated): 22,186'
--   'SOURCE FILES USED:'
--   '- Damac_Lagoons.xlsx (simple 9-column export, 25,353 rows): every one of its (Date, Role, Name)'
--   'DATA CLEANING APPLIED:'
--   '- Phone numbers cleaned of stray characters/spacing, standardized to +CountryCode-Number'
--
-- This is what a user hit when searching and getting back "data cleaning notes
-- and header rows" instead of owners.
--
-- Bounded deliberately at 385980. id 385981 is 'Island Oasis Properties',
-- which the README itself describes as DAMAC's sales/escrow entity appearing
-- as a party on thousands of transactions - a real corporate owner, and it
-- belongs to a different project_name, so it stays.
--
-- Moved to owners_quarantine rather than dropped, so the block can be restored
-- verbatim. The only FK into owners is phones(owner_id) ON DELETE CASCADE, and
-- none of these rows has a phone; owner_search has no FK, so its rows are
-- removed explicitly.

INSERT INTO public.owners_quarantine
SELECT o.*, now(),
       'README/summary sheet imported as owner rows (DAMAC Lagoons Consolidated, ids 385926-385980)'
FROM public.owners o
WHERE o.id BETWEEN 385926 AND 385980
  AND o.project_name = 'DAMAC Lagoons Consolidated';

DELETE FROM public.owner_search
WHERE owner_id IN (SELECT id FROM public.owners_quarantine);

DELETE FROM public.owners
WHERE id IN (SELECT id FROM public.owners_quarantine);


-- ---------------------------------------------------------------------------
-- 4. Orphaned search rows
-- ---------------------------------------------------------------------------
--
-- owner_search has no foreign key to owners, so rows deleted at any point in
-- the past left entries behind. They can never join to anything.

DELETE FROM public.owner_search os
WHERE NOT EXISTS (SELECT 1 FROM public.owners o WHERE o.id = os.owner_id);


-- ---------------------------------------------------------------------------
-- 5. Rollback
-- ---------------------------------------------------------------------------
--
--   -- 1 and 2:
--   UPDATE public.owners o
--   SET full_name       = b.full_name_before,
--       project_name    = b.project_name_before,
--       building        = b.building_before,
--       community_clean = b.community_clean_before
--   FROM public.owners_cleanup_backup b
--   WHERE o.id = b.owner_id;
--
--   -- 3 (column list omits the two quarantine bookkeeping columns):
--   INSERT INTO public.owners
--   SELECT (q.*)::public.owners FROM public.owners_quarantine q;
--
-- ---------------------------------------------------------------------------
