from __future__ import annotations

import pytest

from app.providers.base.errors import ProviderError
from app.providers.softbank_internet.utils import normalize_amount_to_yen


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("7,123円", 7123),
        ("¥8,456", 8456),
        ("請求額 9123", 9123),
    ],
)
def test_normalize_amount_to_yen(value: str, expected: int) -> None:
    assert normalize_amount_to_yen(value) == expected


def test_normalize_amount_to_yen_raises_for_invalid_value() -> None:
    with pytest.raises(ProviderError):
        normalize_amount_to_yen("invalid")

