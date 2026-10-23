# Security and responsible disclosure

This is a hackathon prototype using synthetic data by default. Do not deploy it with real health,
caregiver, or AAC data without a separate privacy, security, legal, clinical, and regulatory review.

## Reporting

Report security concerns privately to the repository maintainers. Do not include personal data or
credentials in a public issue.

## Repository rules

- Secrets stay in untracked environment files or the deployment secret manager.
- FastAPI is the only domain write path.
- Demo reset is disabled outside demo/local mode and requires a token.
- Logs and audit payloads must be minimised and redacted.
- Raw wearable exports and interview identifiers are never committed.
- No production claims or real external contact actions are permitted in this prototype.
