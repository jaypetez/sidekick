"""Lightweight checks that security documentation is present and structured."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_security_policy_exists_and_has_sections() -> None:
    text = (REPO_ROOT / ".github" / "SECURITY.md").read_text(encoding="utf-8")
    assert re.search(r"(?m)^##\s+Reporting a vulnerability", text)
    assert re.search(r"(?m)^##\s+Scope", text)
    assert re.search(r"(?m)^##\s+Supported versions", text)
    assert "Exposed surfaces" in text


def test_operator_guide_exists_and_has_sections() -> None:
    text = (REPO_ROOT / "docs" / "security.md").read_text(encoding="utf-8")
    assert re.search(r"(?m)^##\s+Threat model", text)
    assert re.search(r"(?m)^##\s+Surface-by-surface posture", text)
    assert re.search(r"(?m)^##\s+Operational checklist", text)
    assert re.search(r"(?m)^##\s+Known limitations", text)


def test_readme_links_to_security_docs() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(r"(?m)^##\s+Security", text)
    assert ".github/SECURITY.md" in text
    assert "docs/security.md" in text
