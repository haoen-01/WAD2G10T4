# Contributing

## Branches and pull requests

- `main` should remain runnable.
- Use short-lived `feat/`, `fix/`, `test/`, or `docs/` branches.
- Keep pull requests focused and include a verification note.
- Schema and safety-policy changes require a reviewer.
- Do not rewrite applied Alembic migrations.

## Before opening a pull request

```bash
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test
pnpm demo:smoke
```

Or run `pnpm verify`, which is what CI runs.

## Ownership

- ML and analytics: Member 1.
- API, persistence and agent workflow: Member 2.
- Web experience and demo: Member 3.
- Adapters and safety red-team: Member 4.

The owner makes the final implementation decision after hearing the designated reviewer.

## Commit style

Use concise conventional prefixes:

```text
feat: add rain-aware no-action decision
fix: block expired programme offers
test: cover consent revocation during execution
docs: update offline demo recovery
chore: configure workspace linting
```

## Commit attribution

Every commit must be authored and committed under a teammate's own name. AI assistants (including
Claude) may help write a change, but commits may not be authored, committed or co-authored by
Claude: no `Claude` / `@anthropic.com` identity, no `Co-Authored-By: Claude…`, `Claude-Session:` or
"Generated with Claude Code" lines.

- `pnpm install` and `pnpm setup` point git at `.githooks/`, whose `commit-msg` hook rejects such
  commits. If yours is rejected, set your identity and retry:
  `git config user.name "Your Name" && git config user.email "you@example.com"`.
- CI's `commit-attribution` job checks every commit in a push or pull request with the same rules
  (`scripts/check-commit-attribution.sh`), so `--no-verify` does not get past it.

## Data and safety

Never commit credentials, raw wearable exports, identifiable interview notes, or real senior data.
Every new action must pass deterministic consent and safety rules and have a scenario test.
