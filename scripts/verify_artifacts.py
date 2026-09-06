#!/usr/bin/env python3
"""Verify frozen artifacts against the hashes recorded in TZ v2.0 FINAL section 0.2.

TZ 2.4 treats live specifications (and, per 0.2/6.5, the frozen E-1 research
artifacts and the TZ itself) as immutable: a change is a new version, never
an in-place edit. This script is the automated form of that discipline —
run it standalone (``uv run python scripts/verify_artifacts.py``) or as part
of the test suite (``tests/test_verify_artifacts.py``).

A failure here means one of: a file is missing, a file was edited in place,
or the recorded hash below is wrong. In every case, stop and ask the owner
(TZ 0.3) rather than editing either side to make the check pass.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# path relative to REPO_ROOT -> expected SHA-256 (lowercase hex)
FROZEN_ARTIFACTS: dict[str, str] = {
    "docs/tz/TZ_v2.0_FINAL.md": "468b75e451e853499a041e4671b9200553c9fb4926a9c4a0d6523f99ad88addb",
    "docs/artifacts/edge_thesis_R0_v1.md": "824f35a033c94d1becfbbc8fb444881d140ce96945f5a7d1ea1e561f0090cdcc",
    "docs/artifacts/event_checklist_E1_v1.md": "ed7d8e50f4cbf301ac57e3460109baf8877f7b7e09a4239216350b0c6452580d",
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_all(root: Path = REPO_ROOT) -> list[str]:
    """Check every frozen artifact; return human-readable problems (empty = all OK)."""
    problems = []
    for rel_path, expected in FROZEN_ARTIFACTS.items():
        path = root / rel_path
        if not path.is_file():
            problems.append(f"MISSING: {rel_path}")
            continue
        actual = sha256_of(path)
        if actual != expected:
            problems.append(f"MISMATCH: {rel_path} expected {expected} got {actual}")
    return problems


def main() -> int:
    problems = verify_all()
    if problems:
        print("Frozen artifact verification FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"All {len(FROZEN_ARTIFACTS)} frozen artifacts verified OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
