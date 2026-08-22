# execution

Scope (TZ section 14, 27): order state machine (`DRAFT` .. `UNKNOWN`),
idempotent submission (`client_order_id = hash(intent_id +
execution_attempt)`), ProtectivePolicy activation + broker verification.
Until a position is broker-verified `PROTECTED`, new entries on that
instrument are forbidden and an incident timer runs (TZ 14.3).

No LLM calls from this package, ever (TZ 2.3, 4.2). No brokerage secrets
outside this package's runtime scope (TZ 19.1).

Status: **not started** — first usable (paper broker) version is Stage E5,
gated per `ROADMAP.md`.
