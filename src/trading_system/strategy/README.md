# strategy

Scope (TZ section 27 `Strategy` API, section 5.5): `generate_signal(context)
-> Signal | None` over a frozen `StrategySpecification`. No broker access,
no risk sizing — only event -> signal.

Status: **not started** — Stage E2 (Backtest & Execution Simulation) work,
gated per `ROADMAP.md`. Strategy code path must be identical between
backtest and paper/live (TZ 8.1, E2 acceptance) — this package is written
once, not duplicated per run mode.
