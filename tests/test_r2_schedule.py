"""Exercise the actual workflow eligibility, serialization and selection script."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/content-r2.yml'


def expression(source, context):
    # The workflow currently uses only comparisons, boolean operators and format.
    # Evaluate that restricted subset after replacing all context lookups; no
    # external input is executed and no workflow actions run in these tests.
    source = re.sub(r'\b(?:github|inputs|vars)(?:\.[A-Za-z_][A-Za-z_0-9]*)+',
                    lambda match: repr(context.get(match[0], '')), source)
    source = source.replace('&&', ' and ').replace('||', ' or ')
    return eval(source, {'__builtins__': {}, 'format': lambda value, *args: value.format(*args)})


class ScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text()
        cls.crons = re.findall(r"- cron: '([^']+)'", cls.text)
        cls.eligibility = ' '.join(cls.text.split('    if: >-\n', 1)[1].split('    runs-on:', 1)[0].split())
        cls.group = re.search(r'group: content-r2-\$\{\{ (.+) \}\}', cls.text)[1]
        step = cls.text.split('      - name: Select region and publication mode\n', 1)[1]
        cls.selection = textwrap.dedent(step.split('        run: |\n', 1)[1].split('      - name:', 1)[0])

    def context(self, **changes):
        result = {'github.ref': 'refs/heads/main', 'github.event.repository.default_branch': 'main',
                  'github.event_name': 'schedule',
                  'vars.CONTENT_R2_ENABLED_GLOBAL': 'true', 'vars.CONTENT_R2_ENABLED_JP': 'true'}
        result.update(changes)
        return result

    def test_per_region_fast_switch_replaces_legacy_slots_and_keeps_disabled_editions_off(self):
        self.assertEqual(len(self.crons), 4)
        for global_fast in ('', 'false', 'true'):
            for jp_fast in ('', 'false', 'true'):
                context = self.context(**{'vars.CONTENT_R2_FAST_POLL_GLOBAL': global_fast,
                                           'vars.CONTENT_R2_FAST_POLL_JP': jp_fast})
                actual = []
                for cron in self.crons:
                    context['github.event.schedule'] = cron
                    actual.append(bool(expression(self.eligibility, context)))
                self.assertEqual(actual, [global_fast != 'true', jp_fast != 'true',
                                          global_fast == 'true', jp_fast == 'true'])
                for name in ('GLOBAL', 'JP'):
                    disabled = dict(context, **{'vars.CONTENT_R2_ENABLED_' + name: 'false'})
                    for index in ((0, 2) if name == 'GLOBAL' else (1, 3)):
                        disabled['github.event.schedule'] = self.crons[index]
                        self.assertFalse(expression(self.eligibility, disabled))

    def test_manual_and_both_cadences_share_region_lock_without_cancelling_running_publish(self):
        self.assertIn('      cancel-in-progress: false', self.text)
        for index, cron in enumerate(self.crons):
            region = 'global' if index % 2 == 0 else 'jp'
            context = self.context(**{'github.event.schedule': cron})
            self.assertEqual(expression(self.group, context), region)
            context.update({'github.event_name': 'workflow_dispatch', 'inputs.region': region})
            self.assertEqual(expression(self.group, context), region)
            self.assertTrue(expression(self.eligibility, context))
            context['github.ref'] = 'refs/heads/unreviewed'
            self.assertFalse(expression(self.eligibility, context))

    def test_fast_minutes_are_regular_and_editions_are_staggered(self):
        minute_sets = []
        for cron in self.crons[2:]:
            minutes, *rest = cron.split()
            self.assertEqual(rest, ['*'] * 4)
            slots = list(map(int, minutes.split(',')))
            self.assertEqual([b - a for a, b in zip(slots, slots[1:] + [slots[0] + 60])], [15] * 4)
            minute_sets.append(set(slots))
        self.assertFalse(minute_sets[0] & minute_sets[1])

    def select(self, event, cron='', region='', mode='', auto='true', global_workers='', jp_workers=''):
        with tempfile.TemporaryDirectory() as folder:
            env_path, summary = Path(folder) / 'env', Path(folder) / 'summary'
            env = dict(os.environ, EVENT_NAME=event, SCHEDULE=cron, INPUT_REGION=region,
                       INPUT_MODE=mode, AUTO_PROMOTE_GLOBAL=auto, AUTO_PROMOTE_JP=auto,
                       RESTORE_WORKERS_GLOBAL=global_workers, RESTORE_WORKERS_JP=jp_workers,
                       GITHUB_ENV=str(env_path), GITHUB_STEP_SUMMARY=str(summary), GITHUB_RUN_ID='123')
            result = subprocess.run(['bash', '-c', self.selection], env=env, capture_output=True)
            return result.returncode, env_path.read_text() if env_path.exists() else '', summary.read_text() if summary.exists() else ''

    def test_actual_selection_script_preserves_auto_promote_and_manual_mode(self):
        for index, cron in enumerate(self.crons):
            for auto in ('true', 'false', ''):
                status, env, summary = self.select('schedule', cron=cron, auto=auto)
                self.assertEqual(status, 0)
                self.assertIn('REGION=' + ('global' if index % 2 == 0 else 'jp'), env)
                self.assertIn('MODE=' + ('promote' if auto == 'true' else 'shadow'), env)
                self.assertIn('15 minutes' if index >= 2 else '240 minutes', summary)
                self.assertIn('Selection started at (UTC)', summary)
        status, env, _ = self.select('workflow_dispatch', region='jp', mode='shadow')
        self.assertEqual((status, env), (0, 'REGION=jp\nMODE=shadow\nRESTORE_WORKERS=8\n'))
        self.assertNotEqual(self.select('schedule', cron='unknown')[0], 0)
        self.assertNotEqual(self.select('workflow_dispatch', region='invalid', mode='promote')[0], 0)

    def test_restore_concurrency_is_bounded_per_region_before_expensive_work(self):
        for region in ('global', 'jp'):
            for workers in ('4', '8', '12'):
                options = {region + '_workers': workers}
                status, env, _ = self.select('workflow_dispatch', region=region, mode='shadow', **options)
                self.assertEqual(status, 0)
                self.assertIn('RESTORE_WORKERS=' + workers + '\n', env)
            for bad in ('0', '16', '8\nEXTRA=value', '$(exit 0)', 'invalid'):
                status, env, _ = self.select('workflow_dispatch', region=region, mode='shadow',
                                             **{region + '_workers': bad})
                self.assertNotEqual(status, 0)
                self.assertEqual(env, '')
        status, env, _ = self.select('workflow_dispatch', region='jp', mode='shadow', global_workers='12')
        self.assertEqual(status, 0)
        self.assertIn('RESTORE_WORKERS=8\n', env)


if __name__ == '__main__':
    unittest.main()
