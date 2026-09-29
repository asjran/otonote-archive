from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class SiteWorkflowContractTest(unittest.TestCase):
    def test_fast_check_does_not_regenerate_content(self) -> None:
        package = json.loads(
            (REPO_ROOT / "site/package.json").read_text(encoding="utf-8")
        )
        scripts = package["scripts"]

        self.assertNotIn("catalog", scripts["check"])
        self.assertEqual(
            scripts["check:generated"],
            "npm run catalog && npm run check",
        )

    def test_deploy_will_not_label_dirty_source_as_a_git_release(self) -> None:
        source = (
            REPO_ROOT / "tools/deploy_site.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('git -C "${REPO_ROOT}" diff --quiet -- .', source)
        self.assertIn('git -C "${REPO_ROOT}" diff --cached --quiet -- .', source)
        self.assertIn(
            "Refusing to build a release from tracked uncommitted changes",
            source,
        )
        self.assertIn("git -C \"${REPO_ROOT}\" ls-files --others", source)
        self.assertIn(
            "Refusing to build a release from untracked build inputs",
            source,
        )

    def test_deploy_transfer_preserves_candidate_hard_links(self) -> None:
        deploy_script = (
            REPO_ROOT / "tools/deploy_site.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "rsync -azH --delete --stats",
            deploy_script,
        )
        self.assertIn("--exclude=.DS_Store", deploy_script)

    def test_formal_and_anontokyo_deploy_use_separate_builds(self) -> None:
        formal = (REPO_ROOT / "tools/deploy_site.sh").read_text()
        anon = (REPO_ROOT / "tools/deploy_anontokyo.sh").read_text()
        self.assertIn("npm run build -- --output", formal)
        self.assertNotIn("build_site_matrix.py", formal)
        self.assertIn("npm run build:anontokyo", anon)
        self.assertIn("/anontokyo/index.html", anon)

    def test_deploy_records_terminal_and_rollback_events_best_effort(self) -> None:
        deploy_script = (REPO_ROOT / "tools/deploy_site.sh").read_text(encoding="utf-8")
        self.assertIn("tools/deployment_event.py", deploy_script)
        self.assertIn('record_deployment_event "started"', deploy_script)
        self.assertIn('record_deployment_event "failed"', deploy_script)
        self.assertIn('record_deployment_event "rollback_started"', deploy_script)
        self.assertIn('record_deployment_event "rollback_succeeded"', deploy_script)
        self.assertIn('record_deployment_event "rollback_failed"', deploy_script)
        self.assertIn("exit \"${original_status}\"", deploy_script)

    def test_invalid_arguments_do_not_create_a_deployment_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            event_log = Path(temporary) / "events.jsonl"
            environment = dict(os.environ)
            environment["OURNOTES_DEPLOYMENT_EVENT_LOG"] = str(event_log)
            result = subprocess.run(
                [str(REPO_ROOT / "tools/deploy_site.sh"), "--host", "bad host"],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse(event_log.exists())


if __name__ == "__main__":
    unittest.main()
