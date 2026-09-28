from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# The sign-in names below were observed on the live public page on 2026-09-23.
# Post-login names are intentionally small semantic candidate sets. Run `probe`
# after login before applying mutations and update these names if TimeTree changes.
# "Expand" was observed on the authenticated TimeTree calendar shell on 2026-09-27.
CALENDAR_LIST_NAMES = ("Expand", "Calendar List", "カレンダーリスト", "カレンダー一覧")
SHOW_ONLY_CALENDAR_NAMES = ("Show only this calendar",)
CREATE_EVENT_NAMES = (
    "Create an event",
    "Create a new event",
    "Create event",
    "New event",
    "予定を作成",
    "予定を追加",
)
TITLE_LABELS = ("Title", "Event title", "タイトル", "予定名")
DESCRIPTION_LABELS = ("Description", "Details", "説明", "詳細")
START_DATE_LABELS = ("Start date", "Date", "開始日", "日付")
END_DATE_LABELS = ("End date", "終了日")
SAVE_NAMES = ("Save", "Create", "保存", "作成")
NOTE_NAMES = ("Note",)
NOTE_CONFIRM_NAMES = ("OK",)
MORE_NAMES = ("More", "More options", "Menu", "その他", "その他のオプション", "メニュー", "…", "...")
EDIT_NAMES = ("Edit", "予定を編集", "編集")
DELETE_NAMES = ("Delete", "Delete event", "予定を削除", "削除")
CONFIRM_DELETE_NAMES = ("Delete", "Delete event", "削除する", "削除")


class SelectorNotFound(RuntimeError):
    pass


def visible_locators(locators: Iterable[Any]) -> list[Any]:
    visible: list[Any] = []
    for locator in locators:
        try:
            count = locator.count()
        except Exception:  # noqa: BLE001,S112 - try the next semantic candidate
            continue
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible():
                    visible.append(candidate)
            except Exception:  # noqa: BLE001,S112 - try the next visible candidate
                continue
    return visible


def first_visible(locators: Iterable[Any]) -> Any | None:
    visible = visible_locators(locators)
    return visible[0] if visible else None


def unique_visible(locators: Iterable[Any], action: str) -> Any | None:
    visible = visible_locators(locators)
    if len(visible) > 1:
        raise SelectorNotFound(
            f"Refusing {action}: expected at most one visible semantic match, found {len(visible)}."
        )
    return visible[0] if visible else None


def role_locator(page: Any, role: str, names: tuple[str, ...], *, exact: bool = True) -> Any | None:
    return first_visible(page.get_by_role(role, name=name, exact=exact) for name in names)


def unique_role_locator(
    page: Any,
    role: str,
    names: tuple[str, ...],
    action: str,
    *,
    exact: bool = True,
) -> Any | None:
    return unique_visible(
        (page.get_by_role(role, name=name, exact=exact) for name in names),
        action,
    )


def unique_labeled_locator(page: Any, labels: tuple[str, ...], action: str) -> Any | None:
    return unique_visible((page.get_by_label(label, exact=True) for label in labels), action)


def click_role(page: Any, role: str, names: tuple[str, ...], action: str) -> None:
    locator = unique_role_locator(page, role, names, action)
    if locator is None:
        raise SelectorNotFound(f"Could not find {action} by role={role}; tried accessible names: {names}")
    locator.click()


def fill_labeled(page: Any, labels: tuple[str, ...], value: str, action: str) -> bool:
    locator = unique_labeled_locator(page, labels, action)
    if locator is None:
        return False
    locator.fill(value)
    return True
