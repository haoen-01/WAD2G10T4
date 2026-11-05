# Security

Care+ is a student project that runs on synthetic data. It has not had the privacy, security,
legal or clinical review that real health or family data would need, so do not use it with real
people's data.

## Reporting a problem

Report security concerns privately to the repository maintainers. Do not put personal data,
passwords or keys in a public issue or pull request.

## How the app protects data

- **One write path.** Only the FastAPI server changes data. The web app talks to the server and
  uses Supabase only to sign in.
- **Database locked to the server.** Every table has row-level security with explicit deny
  policies for Supabase's `anon` and `authenticated` roles, so the public key in the browser cannot
  read or write any table. `GET /ready` reports any table that is missing them.
- **Sign-in checked by the server.** With sign-in on, the server verifies each Supabase token and
  enforces roles: a senior sees only their own screens, and family routes are limited to active
  members of that care group.
- **Rules before AI.** Consent, data quality and contact limits are fixed rules in the server. The
  optional AI planner can only reorder or reword options those rules already allow, and the Kaki
  assistant gives a fixed safety reply to emergency, medicine and symptom questions.
- **Demo reset is guarded.** The reset route is refused when `APP_ENV=production`, and with
  sign-in on it needs a signed-in demo operator.
- **No secrets in the browser.** Server keys (database URL, Supabase secret key, AI keys) are set
  only as server environment variables. The browser gets only the Supabase publishable key and the
  API URL.
- **Minimal public calls.** The browser calls two public services (weather and public holidays)
  with no key and sends nothing about the senior.

## Rules for contributors

- Keep secrets in an untracked `.env` file or the hosting provider's secret settings. Never commit
  them; `.env.example` holds placeholders only.
- Never commit real wearable exports, real people's data or interview notes.
- Keep logs and stored evidence to what is needed, without personal details.
- Changes to the decision policy, consent rules, database schema or sign-in need a reviewer.
