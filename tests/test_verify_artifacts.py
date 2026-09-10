from scripts.verify_artifacts import FROZEN_ARTIFACTS, verify_all


def test_all_frozen_artifacts_match_recorded_hashes() -> None:
    problems = verify_all()
    assert problems == [], "\n".join(problems)


def test_frozen_artifact_table_is_not_empty() -> None:
    assert len(FROZEN_ARTIFACTS) >= 3
