# Frozen E-1 artifacts

TZ section 0.2 records two artifacts as already frozen, by hash, before this
repository existed:

| File | SHA-256 |
|---|---|
| `edge_thesis_R0_v1.md` | `824f35a033c94d1becfbbc8fb444881d140ce96945f5a7d1ea1e561f0090cdcc` |
| `event_checklist_E1_v1.md` | `ed7d8e50f4cbf301ac57e3460109baf8877f7b7e09a4239216350b0c6452580d` |

**These files are not yet in this repository.** Their content must come from
wherever the owner/analyst originally produced them — reconstructing text
here would not reproduce the recorded hash and would silently create a
*different*, unfrozen artifact under the same name, which TZ 2.4 (immutable
live specifications) and 0.3 (owner veto rights over frozen artifacts) both
rule out.

Action needed before Stage E-1 step 4 (blind classification) can start:
place the exact original files here (or in `config/checklists/` for the
checklist, matching `config/README.md`) and verify with:

```sh
sha256sum edge_thesis_R0_v1.md event_checklist_E1_v1.md
```

against the table above. If they don't match, do not proceed — treat it as
the artifact having changed, which under TZ 2.4 requires a new version and
re-approval, not a silent substitution.

See `../../ROADMAP.md` for where this sits in the overall stage sequence.
