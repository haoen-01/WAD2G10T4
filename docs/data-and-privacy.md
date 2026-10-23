# Data and privacy rules

## Allowed in this repository

- Reproducible synthetic persona and scenario data.
- Mock AAC programme catalogues labelled as mock.
- Cached public context fixtures with provenance.
- De-identified, derived aggregates from a consenting team member when explicitly approved.

## Never commit

- Raw Apple Health, Garmin, FIT, GPX or other wearable exports.
- Real senior, caregiver or AAC records.
- Identifiable interview notes or recordings.
- Credentials, tokens, connection strings or private keys.

## Demo claims

Synthetic performance validates software and policy behaviour only. It does not validate diagnosis,
clinical risk, health outcomes, population performance or Healthy 365 compatibility.

## Retention

Raw imports should be processed outside Git, reduced to the minimum canonical daily fields, and
deleted after the consented adapter proof. Interview notes should be de-identified and deleted when
no longer needed for the hackathon.

Consent is append-only evidence: a change creates a new record instead of editing history. When
consent is revoked, proposed interventions are immediately marked withdrawn and late responses are
rejected. The senior-facing view exposes opt-out without clinical scores; the coordinator view
shows consent status and reviewer evidence.

Consent gates proactive outreach and inferred preference learning; it does not gate a senior's own
search, an explicit preference statement, the underlying signal analysis, or the ambient weather
fetch -- those are separate scopes and are, by decision, always permitted. See
`docs/adr/0001-consent-scope-model.md` for the full model and what is deferred.
