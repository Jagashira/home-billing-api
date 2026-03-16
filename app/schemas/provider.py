from __future__ import annotations

from pydantic import BaseModel


class ProviderInfo(BaseModel):
    name: str
    display_name: str
    service_type: str
    enabled: bool
    description: str

