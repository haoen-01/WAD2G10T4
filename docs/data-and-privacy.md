# Data and privacy rules

## Allowed in this repository

- Reproducible synthetic persona and scenario data.
- Mock community-programme listings labelled as mock.
- Cached public context fixtures with provenance.
- De-identified, derived aggregates from a consenting team member when explicitly approved.

## Never commit

- Raw Apple Health, Garmin, FIT, GPX or other wearable exports.
- Real senior, family or care-centre records.
- Identifiable interview notes or recordings.
- Credentials, tokens, connection strings or private keys.

## Demo claims

Synthetic results validate software and policy behaviour only. They do not validate diagnosis,
clinical risk, health outcomes, population performance or Healthy 365 compatibility. The watch
on Home is simulated; no real device is connected.

## Retention

Raw imports are processed outside Git, reduced to the minimum canonical daily fields, and deleted
after the consented adapter proof. Interview notes are de-identified and deleted when no longer
needed.

Consent is append-only evidence: a change creates a new record instead of editing history. When
consent is withdrawn, proposed interventions are marked withdrawn at once and late responses are
rejected. Home shows "Consent withdrawn" without any clinical score.

Consent gates proactive outreach and inferred preference learning; it does not gate the underlying
signal analysis or the weather context. See
[`adr/0001-consent-scope-model.md`](adr/0001-consent-scope-model.md) for the full model.

## The Care+ assistant (Kaki)

When `OPENAI_API_KEY` is set (never in the offline profile), each question to the assistant is sent
by the API to OpenAI with the last few turns of the chat and a short summary of what that person can
already see: the senior's name, recent daily steps and a usual day, and appointments in the next two
weeks. Emergencies and questions about medicines or symptoms get a fixed reply and are never sent.
The conversation is not stored by Care+, and the API logs only which source answered. Voice typing
uses the browser's own speech recognition, which in most browsers sends the recording to Google or
Apple; it asks first. See [`adr/0013-care-plus-assistant.md`](adr/0013-care-plus-assistant.md) and
[`assistant.md`](assistant.md).
