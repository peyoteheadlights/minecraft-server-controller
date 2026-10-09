"""What the release workflow checks before it builds anything
(scripts/release_check.py), and the pinned, least-permission workflows."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from agent import __version__, signing
from scripts import api_contract, release_check

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def test_a_matching_tag_with_changelog_api_copy_and_key_passes(monkeypatch):
    monkeypatch.setattr(signing, "UPDATE_PUBLIC_KEY", signing.new_key()[1])
    current = json.loads(json.dumps(api_contract.current_schema()))
    monkeypatch.setattr(
        api_contract, "released_schema", lambda: (f"openapi-{__version__}.json", current)
    )
    assert release_check.problems(f"v{__version__}") == []
    # The saved copy must be this code's API, not an older one.
    monkeypatch.setattr(
        api_contract, "released_schema", lambda: (f"openapi-{__version__}.json", {"paths": {}})
    )
    assert any("isn't the API" in line for line in release_check.problems(f"v{__version__}"))
    notes = release_check.notes(__version__)
    assert notes.startswith("## What's new")
    assert "Unknown publisher" in notes and "gh attestation verify" in notes


def test_a_wrong_tag_or_missing_key_is_refused(monkeypatch):
    monkeypatch.setattr(signing, "UPDATE_PUBLIC_KEY", "")
    found = release_check.problems("v0.0.1")
    assert any("isn't v" in line for line in found)
    assert any("no update-signing public key" in line for line in found)


def test_changelog_sections_are_found_by_version():
    text = "# What's new\n\n## 1.2.0\n\n- new\n\n## 1.1.0\n\n- old\n"
    assert release_check.changelog_section(text, "1.2.0") == "- new"
    assert release_check.changelog_section(text, "1.1.0") == "- old"
    assert release_check.changelog_section(text, "1.3.0") is None


def test_every_action_is_pinned_to_a_commit():
    for path in WORKFLOWS.glob("*.yml"):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.search(r"uses:\s*(\S+)", line)
            if match and not match.group(1).startswith("./"):
                assert re.search(r"@[0-9a-f]{40}\s+# v\d", line), f"{path.name}: {line.strip()}"


def test_workflows_ask_for_least_permissions():
    for path in WORKFLOWS.glob("*.yml"):
        flow = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "permissions" in flow, f"{path.name} has no top-level permissions"
        top = flow["permissions"] or {}
        assert "write" not in str(top.values()), f"{path.name} writes by default"
        for name, job in flow["jobs"].items():
            if job.get("permissions", {}).get("contents") == "write":
                assert (path.name, name) == ("release.yml", "publish"), (path.name, name)
