from __future__ import annotations

import re

from app.providers.base.errors import ErrorCode, ProviderError


def normalize_amount_to_yen(value: str) -> int:
    digits = re.sub(r"[^\d]", "", value)
    if not digits:
        raise ProviderError(
            ErrorCode.PARSE_FAILED,
            f"Could not parse billing amount from value: {value!r}",
        )
    return int(digits)
