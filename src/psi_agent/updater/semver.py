"""Minimal dotted-version comparison for update checks."""

from __future__ import annotations


def _split(version: str) -> tuple[list[object], str]:
    main, _, pre = version.strip().partition("-")
    parts: list[object] = []
    for item in main.split("."):
        if item.isdigit():
            parts.append(int(item))
        else:
            parts.append(item)
    return parts, pre


def compare_versions(left: str, right: str) -> int:
    """Compare two dotted versions; returns -1/0/1.

    Numeric segments compare numerically, non-numeric segments string-wise,
    missing segments count as 0, and a ``-pre`` suffix sorts before the bare
    release (``1.0.5-rc1 < 1.0.5``).
    """
    l_main, l_pre = _split(left)
    r_main, r_pre = _split(right)
    length = max(len(l_main), len(r_main))
    for i in range(length):
        lv = l_main[i] if i < len(l_main) else 0
        rv = r_main[i] if i < len(r_main) else 0
        if isinstance(lv, int) and isinstance(rv, int):
            if lv == rv:
                continue
            return -1 if lv < rv else 1
        ls, rs = str(lv), str(rv)
        if ls == rs:
            continue
        return -1 if ls < rs else 1
    if l_pre == r_pre:
        return 0
    if not l_pre:
        return 1
    if not r_pre:
        return -1
    return -1 if l_pre < r_pre else 1
