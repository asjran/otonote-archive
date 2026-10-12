from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.r2_run_summary import summarize


class SummaryTests(unittest.TestCase):
    def test_known_gate_reasons_and_failed_probes_are_visible_but_untrusted_reasons_are_hidden(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'light-probe.json').write_text('{"status":"blocked","skip":false,"reason":"probe_failed"}')
            (root/'light-check.json').write_text('{"status":"needs_full","reason":"resource_version_changed"}')
            (root/'gate-check.json').write_text('{"status":"needs_production","reason":"token=private-secret"}')
            result = summarize(root, 'failure')
            self.assertIn('Light source probe: `blocked`', result)
            self.assertIn('Reason: `probe_failed`', result)
            self.assertIn('Reason: `resource_version_changed`', result)
            self.assertIn('Verified unchanged gate: `needs_production`', result)
            self.assertNotIn('private-secret', result)

    def test_incomplete_outputs_do_not_hide_original_failure(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for content in ('', '{', '[]', '{"status": []}', '{"status":"private-secret"}'):
                (root/'state-after.json').write_text(content)
                result = summarize(root, 'failure')
                self.assertIn('Workflow result: `failure`', result)
                self.assertNotIn('private-secret', result)

    def test_manifest_budget_is_reported_without_raw_errors(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'state-after.json').write_text('{"status":"checkpointed","manifestBytes":100,"manifestLimitBytes":120,"manifestBudgetWarning":true,"error":"secret"}')
            result = summarize(root, 'success')
            self.assertIn('manifestBytes: `100`', result)
            self.assertIn('80%', result)
            self.assertNotIn('secret', result)
