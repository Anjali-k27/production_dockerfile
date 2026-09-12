"""
epoch_gateway — the EPOCH cluster's north-south API gateway.

Packaged form of the gateway that ran flat as services/fastapi/app/ through
Week 16 (phase5/session4 = 16.1, phase5/session5 = 16.2). Session 17.1 ships
it as an installable package so the production image imports
`epoch_gateway.main:app` instead of a bare `main:app` off the working dir.

Carried forward unchanged from Week 16:
  - JWT verification contract (epoch_gateway.epoch_auth.verify_jwt)
  - PII redaction on the prompt in and the answer out
  - admin-only tool gate ("clinical pdf" / "deliverable" keywords)
  - /v1 (frozen, Deprecation/Sunset/Link headers) + /v2 (live) invoke routes
  - 400-not-500 on malformed JSON

New in 17.1:
  - /health advertises tenant_isolation state
  - per-request tenant binding + cross-tenant rejection (hospital_id claim)
"""

__version__ = "17.1.0"