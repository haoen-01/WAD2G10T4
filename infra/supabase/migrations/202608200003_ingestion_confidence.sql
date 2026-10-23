alter table public.daily_metrics
add column ingestion_confidence double precision not null default 1.0;

update public.alembic_version
set version_num = '9f1a6c02d4e8'
where version_num = '3c430fbc9737';
