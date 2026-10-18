import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import grpc

from tools.growth_login import BOOTSTRAP, LOGIN_SERVICE, GameClient, LoginError
from tools.game_service_status import GameServiceStatus, METHOD, SERVERS, maintenance_metadata, probe

MAINTENANCE = (
    ('x-maintenance-total', '1'),
    ('x-maintenance-start-at', '2026-10-18T02:00:00Z'),
    ('x-maintenance-end-at', '2026-10-18T06:00:00Z'),
    ('x-maintenance-is-emergency', '0'),
    ('x-maintenance-free-text', 'PRIVATE-UPSTREAM-TEXT'),
)


class RpcFailure(grpc.RpcError):
    def __init__(self, message, metadata):
        self.message, self.metadata = message, metadata
    def details(self):
        return self.message
    def trailing_metadata(self):
        return self.metadata
    def code(self):
        return grpc.StatusCode.UNKNOWN


class MaintenanceStatusTests(unittest.TestCase):
    def test_confirmed_total_maintenance_is_bounded_and_does_not_guess_recovery(self):
        result = maintenance_metadata(MAINTENANCE, 'under maintenance')
        self.assertTrue(result['total'])
        self.assertEqual(result['expectedEndAt'], '2026-10-18T06:00:00+00:00')
        self.assertNotIn('PRIVATE', str(result))
        for metadata, text in (((), 'under maintenance'), (MAINTENANCE, 'unavailable'),
                               (MAINTENANCE + (('x-maintenance-total', '0'),), 'under maintenance')):
            self.assertIsNone(maintenance_metadata(metadata, text))

    def test_probe_updates_only_public_request_version_and_stops_before_any_auth(self):
        calls = []
        def request(payload, *, metadata, timeout, wait_for_ready):
            self.assertEqual(payload, b'')
            self.assertLessEqual(timeout, 2.5)
            self.assertFalse(wait_for_ready)
            params = dict(metadata)
            calls.append(params)
            self.assertEqual(set(params), {'x-client-version', 'x-platform'})
            if len(calls) == 1:
                raise RpcFailure('client update required', (('x-client-recommended-version', '1.0.6'),))
            raise RpcFailure('under maintenance', MAINTENANCE)
        with patch('grpc.secure_channel') as channel:
            channel.return_value.__enter__.return_value.unary_unary.return_value = request
            self.assertEqual(probe('global-en', '1.0.3')['status'], 'maintenance')
            self.assertTrue(all(call.args[0] == METHOD for call in
                                channel.return_value.__enter__.return_value.unary_unary.call_args_list))
        self.assertEqual([c['x-client-version'] for c in calls], ['1.0.3', '1.0.6'])

    def test_existing_read_rpc_maps_late_maintenance_without_private_error_text(self):
        with patch('grpc.secure_channel') as channel:
            channel.return_value.__enter__.return_value.unary_unary.return_value.side_effect = RpcFailure('under maintenance', MAINTENANCE)
            with self.assertRaisesRegex(LoginError, '^game_maintenance$'):
                GameClient().rpc(BOOTSTRAP, LOGIN_SERVICE + 'GetServerList')

    def test_transport_failure_is_unknown_not_maintenance_or_available(self):
        with patch('grpc.secure_channel') as channel:
            channel.return_value.__enter__.return_value.unary_unary.return_value.side_effect = RpcFailure('network unavailable', ())
            self.assertEqual(probe('global-hmt', '1.0.6')['status'], 'unknown')

    def test_success_means_only_no_maintenance_signal(self):
        with patch('grpc.secure_channel') as channel:
            channel.return_value.__enter__.return_value.unary_unary.return_value.return_value = b''
            self.assertEqual(probe('global-kr', '1.0.6')['status'], 'no_maintenance_signal')

    def test_visitors_share_one_refresh_and_expired_failure_cannot_keep_old_maintenance(self):
        now, calls, gate = [100], [], threading.Event()
        def observe(server, version):
            gate.wait(2)
            calls.append(server)
            if now[0] > 100:
                raise ValueError('PRIVATE')
            return {'status': 'maintenance', 'maintenance': maintenance_metadata(MAINTENANCE, 'under maintenance')}
        monitor = GameServiceStatus(observe, version='1.0.6', monotonic=lambda: now[0])
        with ThreadPoolExecutor(max_workers=6) as workers:
            pending = [workers.submit(monitor.snapshot) for _ in range(6)]
            gate.set()
            snapshots = [task.result(3) for task in pending]
        self.assertCountEqual(calls, SERVERS)
        snapshots[0]['servers']['global-hmt']['status'] = 'tampered'
        self.assertEqual(monitor.server('global-hmt')['status'], 'maintenance')
        now[0] = 161
        result = monitor.snapshot()
        self.assertTrue(all(row['status'] == 'unknown' for row in result['servers'].values()))
        self.assertNotIn('PRIVATE', str(result))
        self.assertEqual(len(calls), 6)


if __name__ == '__main__':
    unittest.main()
