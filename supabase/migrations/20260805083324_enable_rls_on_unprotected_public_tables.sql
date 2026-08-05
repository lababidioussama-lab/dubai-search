-- Close the rls_disabled_in_public advisories.
-- These 20 public tables had RLS off while anon/authenticated held full
-- SELECT/INSERT/UPDATE/DELETE grants, so anyone with the project URL and the
-- publishable anon key could read or destroy them.
--
-- No policies are added, matching the convention already used by the other 61
-- public tables: all reads/writes go through Edge Functions that use
-- SUPABASE_SERVICE_ROLE_KEY, which bypasses RLS. Zero policies therefore means
-- "no direct client access" while the app keeps working unchanged.

alter table public.dl_new_check                    enable row level security;
alter table public.dld_import_staging              enable row level security;
alter table public.owner_fl                        enable row level security;
alter table public.owner_norm                      enable row level security;
alter table public.owners_raw_data_backup_dl_strip enable row level security;
alter table public.owners_regis_serial_backup      enable row level security;
alter table public.pass_contact                    enable row level security;
alter table public.property_key_map                enable row level security;
alter table public.search_usage                    enable row level security;
alter table public.stats_cache                     enable row level security;
alter table public.support_messages                enable row level security;
alter table public.villa_pass                      enable row level security;
alter table public.wa_contact_meta                 enable row level security;
alter table public.wa_hidden                       enable row level security;
alter table public.wa_lagoons_owners               enable row level security;
alter table public.wa_media                        enable row level security;
alter table public.wa_notes                        enable row level security;
alter table public.wa_quick_replies                enable row level security;
alter table public.wa_settings                     enable row level security;
alter table public.wa_tags                         enable row level security;
