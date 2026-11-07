"""CI .github/workflows/check.yml и шаблон PR: обязательные шаги на месте."""

from __future__ import annotations

from gitrepo import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "check.yml"
TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"

REQUIRED_STEPS = [
    "actions/checkout",
    "astral-sh/setup-uv",
    "uv sync",
    "contains(github.event.pull_request.labels.*.name, 'human-ok')",
    "labeled",
    "scripts/protected_paths.sh",
    "scripts/commit_messages.sh",
    "make check",
    "playwright install chromium",
    "make e2e",
]


def test_workflow_contains_required_steps() -> None:
    content = WORKFLOW.read_text(encoding="utf-8")
    for step in REQUIRED_STEPS:
        assert step in content, f"в check.yml нет шага: {step}"


def test_pr_template_links_openspec_and_tdd() -> None:
    content = TEMPLATE.read_text(encoding="utf-8")
    assert "openspec/changes" in content
    assert "TDD" in content
    assert "human-ok" in content

