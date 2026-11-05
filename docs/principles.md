# Care+ principles

Care+ helps a family look after an older relative who lives on their own. These are the rules the
product and the code keep. A change that breaks one is wrong, however well it works.

## Product boundary

Care+ is a wellness and family-coordination tool, not a medical or emergency system. It never:

- diagnoses anything or predicts disease;
- detects falls or dispatches emergency help;
- gives medication advice (a medicine task is a label the family writes, nothing more);
- contacts a caregiver or anyone else without the senior's consent;
- reads heart rate or SpO2 as a medical signal.

When Care+ does act, it picks the least intrusive action the rules permit, and doing nothing
(`no_action`) is a recorded, valid result.

## Architecture

- The FastAPI server (`server/`) owns every domain state change and every domain database write.
- The Vue web app (`client/`) calls the API with Axios through `client/src/services/careApi.ts`,
  typed with the generated client. It uses Supabase only to sign in and never reads or writes
  Supabase tables; the database denies the browser roles outright.
- The browser's only other calls are display-only public data (the data.gov.sg forecast and
  Nager.Date public holidays, in `services/publicApis.ts`). They carry nothing about the senior,
  and the page still works when they fail.
- Pydantic models → `openapi/silverloop.json` → the generated TypeScript client is the one
  contract path.
- SQLAlchemy 2 and Alembic own the schema.
- Safety and consent rules are deterministic (`server/src/silverloop/policy.py`). No language
  model can bypass them, and the learner only ranks options the rules already permitted.
- The whole demo runs with SQLite, fixture adapters and `LLM_ENABLED=false`.
- Every piece of evidence carries its source, timestamp, confidence and an evidence ID.
- Wearable and data-source adapters stay detachable from the decision path.
- Every behavioural change comes with a scenario (`scenarios/*.yaml`) or test update.

## Data

- Never commit credentials, raw wearable exports, real senior data or interview identifiers.
- Label synthetic, fixture, replayed and future integrations honestly. Real health-data and
  community-programme integrations are future, authorised adapters only.

See [the glossary](glossary.md) for the terms used here and [the architecture](architecture.md)
for how the code keeps these rules.
