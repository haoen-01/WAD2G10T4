-- Mirrors apps/api/alembic/versions/a3f8c72d1e94_enrich_activity_listings.py.
-- Idempotent by construction: `alembic upgrade head` frequently reaches this database before the
-- mirror does, and a bare `add column` then fails and rolls the whole batch back. See the two
-- "Known drift" notes in docs/supabase.md.

alter table public.activity_candidates
  add column if not exists location_postal_code varchar(20),
  add column if not exists description text,
  add column if not exists duration_minutes integer,
  add column if not exists what_to_bring_json jsonb,
  add column if not exists booking varchar(20) not null default 'unknown',
  add column if not exists booking_note varchar(300),
  add column if not exists contact_phone varchar(40),
  add column if not exists contact_note varchar(200),
  add column if not exists getting_there_json jsonb,
  add column if not exists good_to_know_json jsonb;

-- No RLS or trigger changes: `activity_candidates` already carries them from
-- 202609060007, and it is a catalogue rather than evidence, so it is deliberately not append-only.

update public.alembic_version
set version_num = 'a3f8c72d1e94'
where version_num = 'f7c2a9d4e6b3';
