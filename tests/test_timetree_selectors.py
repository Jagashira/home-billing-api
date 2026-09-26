from __future__ import annotations

import pytest

from app.timetree.selectors import SelectorNotFound, first_visible, unique_visible


class FakeCandidate:
    def __init__(self, visible: bool) -> None:
        self._visible = visible

    def is_visible(self) -> bool:
        return self._visible


class FakeLocator:
    def __init__(self, *visibility: bool) -> None:
        self._candidates = [FakeCandidate(value) for value in visibility]

    def count(self) -> int:
        return len(self._candidates)

    def nth(self, index: int) -> FakeCandidate:
        return self._candidates[index]


def test_first_visible_is_available_for_read_only_detection() -> None:
    expected = first_visible((FakeLocator(False, True),))
    assert expected is not None
    assert expected.is_visible()


def test_unique_visible_accepts_one_semantic_match() -> None:
    expected = unique_visible((FakeLocator(False, True),), "safe action")
    assert expected is not None
    assert expected.is_visible()


def test_unique_visible_refuses_ambiguous_mutation_target() -> None:
    with pytest.raises(SelectorNotFound, match="Refusing safe action"):
        unique_visible((FakeLocator(True), FakeLocator(True)), "safe action")
