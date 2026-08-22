# safety

Scope (TZ section 26 `safety` schema; sections 2.5, 10, 11, 12, 13):
Compliance Gate, PolicyEnvelope storage/validation, restricted list
versions, factor limits, Cash Manager, Manipulation Guard, portfolio
allocator, incidents, used-nonce cache (P0+).

This is the Safety Plane (TZ 2.5): its decisions are final and no other
component — including an autonomous agent process — may reverse a
rejection, raise `q_max`, widen the universe, clear a restricted
instrument, raise the capital ceiling, raise leverage, or relax a hard
limit through any public API.

Status: **not started** — Stage E4 ("Safety Core"), gated per `ROADMAP.md`.
