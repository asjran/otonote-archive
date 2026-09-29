from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.docs_status import validate_status_index


class DocsStatusTest(unittest.TestCase):
    def test_repository_status_index_references_existing_documents(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        self.assertEqual(
            validate_status_index(repo_root, repo_root / "docs/STATUS.md"),
            [],
        )

    def test_rejects_unknown_status_and_missing_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            status_path = root / "docs/STATUS.md"
            status_path.write_text(
                "\n".join(
                    [
                        "# Status",
                        "",
                        "| Document | Status | Superseded by | Evidence | Last verified |",
                        "| --- | --- | --- | --- | --- |",
                        "| `docs/missing.md` | `finished` | — | — | 2026-07-26 |",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                validate_status_index(root, status_path),
                [
                    "line 5: unknown document status: finished",
                    "line 5: document does not exist: docs/missing.md",
                ],
            )

    def test_requires_every_design_and_plan_to_be_registered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            specs = root / "docs/superpowers/specs"
            specs.mkdir(parents=True)
            design = specs / "design.md"
            design.write_text("# Design\n", encoding="utf-8")
            status_path = root / "docs/STATUS.md"
            status_path.write_text(
                "\n".join(
                    [
                        "# Status",
                        "",
                        "| Document | Status | Superseded by | Evidence | Last verified |",
                        "| --- | --- | --- | --- | --- |",
                        "| `docs/registered.md` | `historical` | — | — | 2026-07-28 |",
                    ]
                ),
                encoding="utf-8",
            )
            (root / "docs/registered.md").write_text(
                "# Registered\n",
                encoding="utf-8",
            )

            self.assertEqual(
                validate_status_index(root, status_path),
                [
                    "design document is not registered: "
                    "docs/superpowers/specs/design.md"
                ],
            )


if __name__ == "__main__":
    unittest.main()
