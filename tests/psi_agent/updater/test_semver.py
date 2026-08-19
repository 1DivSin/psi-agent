from psi_agent.updater.semver import compare_versions


def test_numeric_segments() -> None:
    assert compare_versions("1.0.4", "1.0.5") == -1
    assert compare_versions("1.0.10", "1.0.9") == 1
    assert compare_versions("1.0.5", "1.0.5") == 0


def test_short_and_long_forms() -> None:
    assert compare_versions("1.1", "1.0.9") == 1
    assert compare_versions("1.0", "1.0.0") == 0


def test_pre_release_sorts_below_release() -> None:
    assert compare_versions("1.0.5-rc1", "1.0.5") == -1
    assert compare_versions("1.0.5", "1.0.5-rc1") == 1


def test_mixed_segments_do_not_crash() -> None:
    assert compare_versions("1.a", "1.2") in (-1, 1)
