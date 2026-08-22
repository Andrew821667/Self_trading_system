# risk

Scope (TZ section 9, Stage E4 "Safety Core"): `Risk Engine.evaluate(state,
intent, rules, policy) -> RiskDecision` with the fixed check ordering in
TZ 9.2 (mode -> restricted list -> blackout -> public source basis ->
manipulation guard -> ... -> min viable quantity), plus dual compute
(TZ 9.3) from P0 onward.

No LLM calls from this package, ever (TZ 2.3, 4.2): risk decisions must be
deterministic and replayable without re-invoking any model.

Status: **not started** — gated per `ROADMAP.md`. Property-based invariants
this package must satisfy once built (TZ 22.2): approved q never exceeds
q_max; factor exposure never exceeds policy max; cash reserve never drops
below minimum; QUARANTINE strategies get zero new risk; a restricted
instrument always rejects.
