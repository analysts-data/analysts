"""Сборка реализаций портов из `Settings`; без запросов наружу."""

import httpx

from cqa.adapters.org_api import OrgApi
from cqa.services.ingest import OrgDialogSource
from cqa.settings import Settings


def build_source(settings: Settings) -> OrgDialogSource:
    url = settings.org_api_url.get_secret_value() if settings.org_api_url else None
    return OrgDialogSource(settings, OrgApi(url, httpx.AsyncClient()))
