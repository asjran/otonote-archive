import fcntl
import json
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from tools.r2_dispatch import NoRedirect, dispatch


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.token = self.root / 'token'
        self.token.write_text('github_pat_test_secret')
        self.token.chmod(0o600)
        self.state = self.root / 'state'
        self.sent = []

    def tearDown(self):
        self.temp.cleanup()

    def send(self, request, timeout):
        self.sent.append((request, timeout))
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.getcode.return_value = 204
        return response

    def run_dispatch(self, now=1800, region='global', send=None):
        return dispatch('stonesver/otonote', region, self.token, self.state,
                        now=now, send=send or self.send)

    def test_acceptance_is_not_completion_and_mode_respects_actions_policy(self):
        result = self.run_dispatch()
        self.assertEqual(result['status'], 'accepted')
        request, timeout = self.sent[0]
        self.assertEqual(timeout, 15)
        self.assertEqual(request.full_url, 'https://api.github.com/repos/stonesver/otonote/actions/workflows/content-r2.yml/dispatches')
        self.assertEqual(json.loads(request.data), {'ref': 'main', 'inputs': {'region': 'global', 'mode': 'auto'}})
        self.assertNotIn('secret', json.dumps(result))
        self.assertEqual(json.loads((self.state/'global.json').read_text()), result)
        self.assertEqual((self.state/'global.json').stat().st_mode & 0o777, 0o600)

    def test_one_attempt_per_slot_per_region_and_no_missed_slot_replay(self):
        self.run_dispatch()
        self.assertEqual(self.run_dispatch(1850)['reason'], 'slot_already_attempted')
        self.assertEqual(self.run_dispatch(1700)['reason'], 'slot_already_attempted')
        self.run_dispatch(region='jp')
        self.run_dispatch(90000)
        self.assertEqual(len(self.sent), 3)

    def test_timeout_preserves_last_acceptance_and_does_not_retry_ambiguous_send(self):
        first = self.run_dispatch()
        send = Mock(side_effect=URLError('secret internal error'))
        result = self.run_dispatch(2700, send=send)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['lastAcceptedAt'], first['lastAcceptedAt'])
        self.assertNotIn('secret', json.dumps(result))
        self.assertEqual(self.run_dispatch(2800)['status'], 'skipped')
        self.assertEqual(send.call_count, 1)

    def test_http_failure_reports_only_status_code(self):
        for index, body in enumerate((None, io.BytesIO(b'secret response body'))):
            send = Mock(side_effect=HTTPError('https://api.github.com', 401, 'secret', {}, body))
            result = self.run_dispatch(now=1800 + index * 900, send=send)
            self.assertEqual((result['status'], result['httpStatus']), ('failed', 401))
            self.assertNotIn('secret', json.dumps(result))
            if body is not None: self.assertTrue(body.closed)

    def test_redirects_are_rejected_before_credentials_can_leave_github(self):
        with self.assertRaises(HTTPError):
            NoRedirect().redirect_request(Mock(full_url='https://api.github.com'), None,
                                          302, 'redirect', {}, 'https://elsewhere.invalid')

    def test_concurrent_dispatch_is_skipped(self):
        self.state.mkdir(mode=0o700)
        with (self.state/'global.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_dispatch()['reason'], 'already_running')
        self.assertEqual(self.sent, [])

    def test_public_or_linked_credentials_and_state_are_rejected(self):
        self.token.chmod(0o644)
        with self.assertRaises(ValueError): self.run_dispatch()
        self.token.chmod(0o600)
        link = self.root/'linked-token'
        link.symlink_to(self.token)
        with self.assertRaises(OSError):
            dispatch('stonesver/otonote', 'global', link, self.state, now=1800, send=self.send)
        self.state.chmod(0o755)
        with self.assertRaises(ValueError): self.run_dispatch()
        self.assertEqual(self.sent, [])

    def test_invalid_target_and_corrupt_state_never_dispatch(self):
        for repo in ('a/..', 'a/b/c', 'https://elsewhere.invalid', 'a/b?token=x'):
            with self.assertRaises(ValueError):
                dispatch(repo, 'global', self.token, self.state, now=1800, send=self.send)
        self.state.mkdir(mode=0o700)
        (self.state/'global.json').write_text('{')
        (self.state/'global.json').chmod(0o600)
        with self.assertRaises(ValueError): self.run_dispatch()
        self.assertEqual(self.sent, [])
