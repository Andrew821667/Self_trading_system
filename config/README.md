# Configuration as code (TZ section 28)

Everything under `config/` is version-controlled and, once activated, is
immutable: an activation record carries `version`, `hash`, `effective_from`,
`approved_by` (TZ 28). Nothing here is edited in place once live — a change
is a new version alongside the old one, promoted through whatever gate
applies to that config category (checklist revisions, for instance, create a
new artifact version per TZ 0.3 and never touch a frozen one).

None of these directories hold live content yet: the registries and loaders
that will read them are Stage E0/E4 work, gated per `../ROADMAP.md`. The
directories exist now so config layout is decided once, matching TZ 28:

| Directory | Content |
|---|---|
| `risk_rules/` | Risk Engine `RuleSet` versions (TZ 9) |
| `strategy_specs/` | `StrategySpecification` versions (TZ 5.5) |
| `execution_specs/` | `ExecutionSpecification` versions (TZ 5.6) |
| `protective_policies/` | `ProtectivePolicy` versions (TZ 5.7) |
| `event_schemas/` | Structured event JSON schemas, by `schema_version` (TZ 6.3, 20) |
| `checklists/` | Reserved for a pipeline-loadable copy of frozen checklists, once Stage E1 builds the loader. The canonical frozen original + hash registry lives in `../docs/artifacts/` (TZ 0.2) — do not fork content between the two locations. |
| `restricted_list/` | Restricted instrument list versions (TZ 26 `restricted_list_versions`) |
| `factor_limits/` | Factor exposure limit sets (TZ 26 `factor_limits`) |
| `cash_policy/` | Cash Manager policy (TZ 11) |
| `autonomy_policy/` | Autonomy level / downgrade rules (TZ 17, 23) |
| `capital_ladder/` | Capital scaling ladder steps (TZ 5.10 `capital_scaling_ladder`) |
