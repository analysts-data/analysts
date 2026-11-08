"""Ports between tracks, verbatim from design/ports.md."""

from collections.abc import Sequence
from typing import Protocol

from cqa.domain.models import Checklist, Criterion, Dialog, DialogEvaluation, IngestResult
from cqa.domain.prosody import Tracks


class DialogSource(Protocol):  # implemented by OrgDialogSource (dialog-ingest)
    async def fetch(self, group_id: str, url: str | None = None) -> IngestResult: ...  # Invalid | Upstream
    def upload(self, raw: bytes) -> IngestResult: ...  # Invalid
    async def audio_link(self, audio_url: str) -> str | None: ...  # fresh MP3 link; None if it failed


class Evaluator(Protocol):  # implemented by LlmEvaluator (llm-evaluation)
    async def evaluate(
        self, dialog: Dialog, checklist: Checklist, criteria: Sequence[Criterion]
    ) -> DialogEvaluation: ...


class Voice(Protocol):  # implemented by PraatVoice (dialog-ingest, prosody)
    async def tracks(self, link: str) -> Tracks | None: ...  # None if the record did not download or decode
