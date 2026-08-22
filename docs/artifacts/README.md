# Frozen E-1 artifacts

TZ section 0.2 records two artifacts as frozen, by hash, before this
repository existed. Both are now present here, verified byte-for-byte
against those hashes before commit:

| File | SHA-256 | Status |
|---|---|---|
| [`edge_thesis_R0_v1.md`](edge_thesis_R0_v1.md) | `824f35a033c94d1becfbbc8fb444881d140ce96945f5a7d1ea1e561f0090cdcc` | ✅ verified 2026-08-22 |
| [`event_checklist_E1_v1.md`](event_checklist_E1_v1.md) | `ed7d8e50f4cbf301ac57e3460109baf8877f7b7e09a4239216350b0c6452580d` | ✅ verified 2026-08-22 |

Verification is automated: `scripts/verify_artifacts.py` re-checks these
hashes (plus the TZ document's own hash) and runs as part of the test suite
(`tests/test_verify_artifacts.py`). Run it directly with:

```sh
uv run python scripts/verify_artifacts.py
```

## Rule for any future change

These files are frozen (TZ 2.4): a change is a new version, never an
in-place edit. If a future copy of either file does not hash to the value
recorded above and in `scripts/verify_artifacts.py`, **stop and ask the
owner** — do not silently accept the new content, and do not "fix" the file
to match the old hash. Under TZ 2.4/0.3 this is either an integrity problem
or the start of a new, separately-approved version (e.g.
`event_checklist_E1_v1.1.md`), and only the owner decides which.

See `../../ROADMAP.md` for where this sits in the overall stage sequence.
