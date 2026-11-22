"""Diff 2 bản config cho giao diện 2 cột (FR-63)."""
from difflib import SequenceMatcher


def diff_configs(a: str, b: str) -> list[dict]:
    """Trả list[{kind: same|add|del, left, right}]; dòng thay đổi = del (trái) rồi add (phải)."""
    la, lb = a.splitlines(), b.splitlines()
    rows: list[dict] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, la, lb, autojunk=False).get_opcodes():
        if tag == "equal":
            rows += [{"kind": "same", "left": x, "right": x} for x in la[i1:i2]]
            continue
        rows += [{"kind": "del", "left": x, "right": None} for x in la[i1:i2]]
        rows += [{"kind": "add", "left": None, "right": x} for x in lb[j1:j2]]
    return rows
