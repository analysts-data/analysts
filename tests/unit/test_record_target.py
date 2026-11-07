import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_make_record_rewrites_exactly_the_replayed_calls() -> None:
    out = subprocess.run(
        ["make", "-n", "record"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    assert 'CQA_LLM_MODE=record uv run pytest -m "cassette or e2e"' in out
