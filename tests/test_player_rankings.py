import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from backend.player_rankings import query_player_rankings, validate_observation
from tools.import_player_rankings import publish


class PlayerRankingTests(unittest.TestCase):
    def snapshot(self, server="jp"):
        return {"schemaVersion": 1, "serverId": server, "observedAt": "2026-09-30T00:00:00Z", "expiresAt": "2026-09-30T01:00:00Z", "boards": [
            {"eventId": "event-1", "eventName": "Example", "type": "event-points", "entries": [
                {"playerId": str(i), "name": "Player", "rank": i, "score": 100 - i} for i in (1, 2, 3)]}]}

    def test_independent_servers_and_expired_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / "input.json"
            source.write_text(json.dumps(self.snapshot())); target = publish(source, root, "jp")
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)
            self.assertEqual(query_player_rankings(root, server="global-en")["status"], "unavailable")
            result = query_player_rankings(root, server="jp", now=datetime(2026, 9, 30, 2, tzinfo=timezone.utc))
            self.assertEqual(result["status"], "stale")
            self.assertEqual(result["entries"][0]["playerKey"], "jp:1")

    def test_cursor_cannot_cross_server_event_or_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / "input.json"
            for server in ("jp", "global-en"):
                source.write_text(json.dumps(self.snapshot(server))); publish(source, root, server)
            first = query_player_rankings(root, server="jp", limit=1)
            second = query_player_rankings(root, server="jp", limit=1, cursor=first["nextCursor"])
            self.assertEqual(second["entries"][0]["rank"], 2)
            with self.assertRaises(ValueError):
                query_player_rankings(root, server="global-en", cursor=first["nextCursor"])
            data = self.snapshot(); data["boards"][0]["entries"][0]["score"] = 200
            source.write_text(json.dumps(data)); publish(source, root, "jp")
            with self.assertRaises(ValueError):
                query_player_rankings(root, server="jp", cursor=first["nextCursor"])

    def test_wrong_identity_and_duplicate_players_rejected(self):
        with self.assertRaises(ValueError): validate_observation(self.snapshot(), "global-kr")
        data = self.snapshot(); data["boards"][0]["entries"].append(data["boards"][0]["entries"][0])
        with self.assertRaises(ValueError): validate_observation(data, "jp")

    def test_empty_success_is_distinct_from_missing_board(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / "input.json"; data = self.snapshot()
            data["boards"][0]["entries"] = []; source.write_text(json.dumps(data)); publish(source, root, "jp")
            self.assertEqual(query_player_rankings(root, server="jp", now=datetime(2026, 9, 30, 0, 5, tzinfo=timezone.utc))["status"], "empty")
            self.assertEqual(query_player_rankings(root, server="jp", board="music")["status"], "unavailable")

    def test_http_route_is_server_scoped_and_not_cached(self):
        from fastapi.testclient import TestClient
        from tests.test_query_http import _make_config, _build_app
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = _make_config(root)
            source = root / "input.json"
            source.write_text(json.dumps(self.snapshot()))
            publish(source, config.data_root / "observations", "jp")
            with TestClient(_build_app(config)) as client:
                result = client.get("/api/v1/player-rankings?server=jp&limit=1")
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.headers["cache-control"], "no-store")
                self.assertEqual(result.json()["entries"][0]["playerKey"], "jp:1")
                self.assertEqual(client.get("/api/v1/player-rankings?server=global-hmt").json()["entries"], [])
                self.assertEqual(client.get("/api/v1/player-rankings?server=global").status_code, 400)
                self.assertEqual(client.get("/api/v1/player-rankings?server=jp&cursor=broken").status_code, 400)


if __name__ == "__main__": unittest.main()
