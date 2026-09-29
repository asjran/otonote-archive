from __future__ import annotations

import unittest

from tools.anontokyo_staff_assignment import build_staff_assignment_evidence


class AnonTokyoStaffAssignmentEvidenceTest(unittest.TestCase):
    def test_builds_verified_global_capacity_schedule(self) -> None:
        evidence = build_staff_assignment_evidence(
            roles=[
                {"_id": 1, "_iconPath": "cashier"},
                {"_id": 2, "_iconPath": "sales"},
                {"_id": 3, "_iconPath": "restock"},
            ],
            attributes=[
                {"_id": 1, "_defaultValue": 1},
                {"_id": 2, "_defaultValue": 1},
                {"_id": 19, "_defaultValue": 1},
            ],
            player_levels=[
                {"_level": 1, "_reward": ""},
                {"_level": 5, "_reward": "5,19,1;5,1,1"},
                {"_level": 6, "_reward": "5,2,1"},
                {"_level": 20, "_reward": ""},
            ],
        )

        capacities = {row["level"]: row["capacities"] for row in evidence["capacityByLevel"]}
        self.assertEqual(capacities[1], {"cashier": 1, "sales": 1, "restock": 1})
        self.assertEqual(capacities[4], {"cashier": 1, "sales": 1, "restock": 1})
        self.assertEqual(capacities[5], {"cashier": 2, "sales": 1, "restock": 1})
        self.assertEqual(capacities[6], {"cashier": 2, "sales": 2, "restock": 1})
        self.assertEqual(capacities[20], {"cashier": 2, "sales": 2, "restock": 1})
        self.assertEqual(evidence["freePreviewCapacities"], capacities[20])

    def test_cashier_capacity_is_bounded_by_checkout_capacity(self) -> None:
        evidence = build_staff_assignment_evidence(
            roles=[{"_id": 1}, {"_id": 2}, {"_id": 3}],
            attributes=[
                {"_id": 1, "_defaultValue": 2},
                {"_id": 2, "_defaultValue": 1},
                {"_id": 19, "_defaultValue": 1},
            ],
            player_levels=[],
        )

        self.assertEqual(
            evidence["capacityByLevel"][0]["capacities"]["cashier"],
            1,
        )

    def test_rejects_missing_verified_role_rows(self) -> None:
        with self.assertRaisesRegex(ValueError, "role IDs 1, 2 and 3"):
            build_staff_assignment_evidence(
                roles=[{"_id": 1}],
                attributes=[
                    {"_id": 1, "_defaultValue": 1},
                    {"_id": 2, "_defaultValue": 1},
                    {"_id": 19, "_defaultValue": 1},
                ],
                player_levels=[],
            )


if __name__ == "__main__":
    unittest.main()
