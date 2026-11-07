"""GET /api/state: everything the UI needs in one object (review-workflow design, decisions 9-10)."""

from cqa.domain.models import Mode
from cqa.settings import Settings


def mode_from_settings(settings: Settings) -> Mode:
    return Mode(
        where=settings.data_where,
        anonymized=settings.anonymize,
        model=settings.llm_model,
        verifier=settings.verifier,
    )
