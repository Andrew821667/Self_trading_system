# intelligence

Scope (TZ section 6, Stage E1): Source Registry, ingestion, document store,
parser/normalizer, structured extractor, event classifier, ambiguity
resolution, version pinning + golden extraction regression set.

Status: **not started** — gated on Stage E0 (TZ 31), which itself opens only
on a CONFIRMED EdgeThesis verdict. See `ROADMAP.md` at the repo root.

Key invariants this package must enforce once built (do not relax these when
implementing):
- `legal_use_status` is enforced by ingestion itself, not decided per-use
  (TZ 6.1). See `trading_system.domain.public_source.LegalUseStatus`.
- Ambiguity is structural (missing field / conflicting sources / dual-run
  extraction disagreement / unresolved instrument), never a confidence
  self-estimate (TZ 6.4). See `trading_system.domain.structured_event`.
- `extraction_model` + `prompt_version` are frozen per strategy version and
  regression-tested against a golden set before any change reaches live
  (TZ 6.5).
