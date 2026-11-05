# Care+ repository instructions

## Product boundary

Care+ is a wellness and AAC outreach workflow. Never add diagnosis, disease prediction,
fall detection, emergency dispatch, medication advice, unconsented caregiver contact, or direct
interpretation of heart rate/SpO2 as a medical signal.

## Architecture invariants

- FastAPI owns domain state transitions and all domain database writes.
- The Vue web app uses the API contract and never writes directly to Supabase tables.
- Pydantic/OpenAPI is the cross-language contract source.
- SQLAlchemy 2 and Alembic own the schema; do not introduce Prisma.
- Safety and consent rules are deterministic and cannot be bypassed by an LLM.
- The complete demo must work with SQLite, fixture adapters, and `LLM_ENABLED=false`.
- All evidence includes source, timestamps, confidence, and an evidence ID.
- Preserve explicit `NO_ACTION` as a valid audited result.

## Delivery discipline

- Prefer a complete observable loop over breadth.
- Keep ORCA and wearable imports detachable.
- Add or update scenario tests for every behavioural change.
- Never commit raw wearable exports, real senior data, credentials, or interview identifiers.
- Label synthetic, fixture, replayed, and future integrations honestly.
