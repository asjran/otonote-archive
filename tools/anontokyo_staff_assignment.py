"""Normalize evidence-backed AnonTokyo staff-assignment capacity rules."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


ROLE_DEFINITIONS = (
    {"sourceId": "1", "id": "cashier", "attributeId": "1"},
    {"sourceId": "2", "id": "sales", "attributeId": "2"},
    {"sourceId": "3", "id": "restock", "attributeId": None},
)
CHECKOUT_ATTRIBUTE_ID = "19"
MAX_PLAYER_LEVEL = 20


def _integer(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number


def _attribute_defaults(attributes: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    return {
        str(row.get("_id")): max(0, _integer(row.get("_defaultValue")))
        for row in attributes
    }


def _attribute_rewards(value: Any) -> list[tuple[str, int]]:
    rewards: list[tuple[str, int]] = []
    if value in (None, ""):
        return rewards
    for group in str(value).split(";"):
        parts = group.split(",")
        if len(parts) != 3 or parts[0] != "5":
            continue
        amount = _integer(parts[2])
        if amount:
            rewards.append((parts[1], amount))
    return rewards


def build_staff_assignment_evidence(
    *,
    roles: Iterable[Mapping[str, Any]],
    attributes: Iterable[Mapping[str, Any]],
    player_levels: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the verified 1–20 role-capacity schedule from Global Master rows.

    Native ``ATRoleconfigDisplayPresenter.RowLimit`` maps role rows 0/1 to
    attributes 1/2, bounds cashier capacity by active checkout desks, and
    returns a constant one for the restocking row.
    """

    role_rows = {str(row.get("_id")): row for row in roles}
    required_role_ids = {item["sourceId"] for item in ROLE_DEFINITIONS}
    if not required_role_ids.issubset(role_rows):
        raise ValueError("AnonTokyo staff assignment requires role IDs 1, 2 and 3")

    defaults = _attribute_defaults(attributes)
    required_attribute_ids = {"1", "2", CHECKOUT_ATTRIBUTE_ID}
    if not required_attribute_ids.issubset(defaults):
        raise ValueError("AnonTokyo staff assignment requires attribute IDs 1, 2 and 19")

    rewards_by_level: dict[int, list[tuple[str, int]]] = {}
    for row in player_levels:
        level = _integer(row.get("_level"))
        if not 1 <= level <= MAX_PLAYER_LEVEL:
            continue
        rewards_by_level.setdefault(level, []).extend(
            _attribute_rewards(row.get("_reward"))
        )

    values = dict(defaults)
    capacity_by_level: list[dict[str, Any]] = []
    for level in range(1, MAX_PLAYER_LEVEL + 1):
        for attribute_id, amount in rewards_by_level.get(level, []):
            values[attribute_id] = values.get(attribute_id, 0) + amount
        capacities = {
            "cashier": min(values["1"], values[CHECKOUT_ATTRIBUTE_ID]),
            "sales": values["2"],
            "restock": 1,
        }
        capacity_by_level.append({"level": level, "capacities": capacities})

    projected_roles = []
    for definition in ROLE_DEFINITIONS:
        row = role_rows[definition["sourceId"]]
        projected_roles.append(
            {
                "sourceId": definition["sourceId"],
                "id": definition["id"],
                "iconKey": str(row.get("_iconPath") or "") or None,
            }
        )

    return {
        "schemaVersion": 1,
        "roles": projected_roles,
        "capacityByLevel": capacity_by_level,
        "freePreviewCapacities": dict(capacity_by_level[-1]["capacities"]),
        "cashierCapacityRule": "min_role_limit_and_checkout_count",
    }
