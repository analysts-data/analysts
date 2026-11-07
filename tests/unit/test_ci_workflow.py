"""CI .github/workflows/check.yml и шаблон PR: обязательные шаги на месте."""

from __future__ import annotations

import subprocess

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


def test_make_e2e_passes_without_e2e_tests_yet() -> None:
    """Пустой набор e2e-тестов не должен ломать CI (pytest выходит с кодом 5); браузер здесь не нужен."""
    result = subprocess.run(
        ["make", "e2e", "ARGS=-k no_such_e2e_test"], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
