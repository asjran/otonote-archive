"""Read published player observations with server- and snapshot-bound pagination."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path

SERVERS = {"jp", "global-hmt", "global-en", "global-kr"}
BOARDS = {"event-points", "music", "total-music"}
FINAL_EVENT_ID = re.compile(r"[1-9][0-9]*")
FINAL_METADATA_NAME = re.compile(r"event-([1-9][0-9]*)-post-end\.meta\.json")
SHA256 = re.compile(r"[a-f0-9]{64}")


def final_archive_paths(root: Path, server: str, event_id: str) -> tuple[Path, Path]:
    if server not in SERVERS or not isinstance(event_id, str) or not FINAL_EVENT_ID.fullmatch(event_id):
        raise ValueError("invalid final ranking identity")
    folder = root / server / "archive"
    stem = f"event-{event_id}-post-end"
    return folder / f"{stem}.json", folder / f"{stem}.meta.json"


def final_archive_metadata(value: dict, server: str, raw: bytes) -> dict:
    validate_observation(value, server)
    boards = value["boards"]
    identities = {board["eventId"] for board in boards}
    names = {board.get("eventName") for board in boards}
    event_id = next(iter(identities)) if len(identities) == 1 else None
    event_name = next(iter(names)) if len(names) == 1 else None
    if (len(identities) != 1 or len(names) != 1 or not boards
            or not FINAL_EVENT_ID.fullmatch(event_id)
            or not isinstance(event_name, str) or not event_name):
        raise ValueError("invalid final ranking snapshot")
    return {"schemaVersion": 1, "eventId": event_id, "eventName": event_name,
            "observedAt": value["observedAt"], "sha256": hashlib.sha256(raw).hexdigest()}


def list_final_archives(root: Path, server: str) -> dict[str, dict]:
    folder = root / server / "archive"
    if not folder.is_dir():
        return {}
    result = {}
    for path in folder.glob("event-*-post-end.meta.json"):
        match = FINAL_METADATA_NAME.fullmatch(path.name)
        if match is None:
            continue
        try:
            if path.stat().st_size > 4096:
                continue
            metadata = json.loads(path.read_text())
            data_path, _ = final_archive_paths(root, server, match[1])
            if (not isinstance(metadata, dict) or metadata.get("schemaVersion") != 1
                    or metadata.get("eventId") != match[1] or not data_path.is_file()
                    or not isinstance(metadata.get("eventName"), str) or not metadata["eventName"]
                    or not isinstance(metadata.get("observedAt"), str)
                    or not SHA256.fullmatch(str(metadata.get("sha256", "")))):
                continue
            result[match[1]] = metadata
        except (OSError, ValueError, TypeError):
            continue
    return result


PROFILE_IMAGE_HOSTS = {'l14-prod-hk-patch-sirius.gamerfusiontech.com',
                       'l12-prod-hk-patch-sirius.gamerfusiontech.com',
                       'l14-prod-sg-patch-sirius.bilibiligame.net',
                       'l12-prod-sg-patch-sirius.bilibiligame.net'}


def public_player_profile(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('invalid public player profile')
    avatar = value.get('avatarMasterId')
    if avatar is not None and (type(avatar) is not int or not 1 <= avatar <= (1 << 53) - 1):
        raise ValueError('invalid public avatar')
    images = value.get('profileCardImages', [])
    if not isinstance(images, list) or len(images) > 8:
        raise ValueError('invalid public profile images')
    result = []
    for url in images:
        if not isinstance(url, str) or len(url) > 2048:
            raise ValueError('invalid public profile image')
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in PROFILE_IMAGE_HOSTS
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.query or parsed.fragment or not parsed.path.startswith('/')
                or any(part in ('.', '..') for part in parsed.path.split('/'))
                or any(ord(char) < 33 for char in url)):
            raise ValueError('invalid public profile image')
        if url not in result:
            result.append(url)
    return {'avatarMasterId': avatar, 'profileCardImages': result}


def event_schedule(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or not isinstance(value.get('eventId'), str)
            or not FINAL_EVENT_ID.fullmatch(value['eventId'])):
        raise ValueError('invalid ranking schedule')
    result = {'eventId': value['eventId']}
    for key in ('startAt', 'endAt'):
        if not isinstance(value.get(key), str) or len(value[key]) > 64:
            raise ValueError('invalid ranking schedule')
        stamp = datetime.fromisoformat(value[key].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('invalid ranking schedule')
        result[key] = stamp.isoformat()
    if datetime.fromisoformat(result['endAt']) < datetime.fromisoformat(result['startAt']):
        raise ValueError('invalid ranking schedule')
    return result


def schedule_state(schedule, now):
    if not schedule:
        return 'unknown'
    start = datetime.fromisoformat(schedule['startAt'])
    end = datetime.fromisoformat(schedule['endAt'])
    return 'upcoming' if now < start else 'ended' if now > end else 'active'


def public_high_score_deck(value):
    """Validate and project the public score-time deck; never forward raw fields."""
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get('cards'), list) or len(value['cards']) > 5:
        raise ValueError('invalid high score deck')

    def number(value, minimum, maximum, optional=False):
        if optional and value is None:
            return None
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError('invalid deck number')
        return value

    def card(value, member):
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError('invalid deck card')
        result = {'masterId': number(value.get('masterId'), 1, (1 << 53) - 1),
                  'exp': number(value.get('exp'), 0, (1 << 31) - 1, True),
                  'rank': number(value.get('rank'), 1, 5, True)}
        if member:
            result.update(awake=number(value.get('awake'), 1, 5, True),
                          liveSkillLevel=number(value.get('liveSkillLevel'), 1, 5, True),
                          performanceSkillLevel=number(value.get('performanceSkillLevel'), 1, 5, True))
        return result

    result = {'totalPower': number(value.get('totalPower'), 1, (1 << 31) - 1, True), 'cards': []}
    slots, orders = set(), set()
    for row in value['cards']:
        if not isinstance(row, dict):
            raise ValueError('invalid deck slot')
        slot = number(row.get('slot'), 0, 4)
        order = number(row.get('performanceOrder'), 0, 4)
        if slot in slots or order in orders:
            raise ValueError('duplicate deck slot or order')
        slots.add(slot); orders.add(order)
        result['cards'].append({'slot': slot, 'performanceOrder': order,
                                'member': card(row.get('member'), True), 'support': card(row.get('support'), False)})
    result['cards'].sort(key=lambda row: row['slot'])
    return result


def validate_observation(value: dict, server: str) -> dict:
    if not isinstance(value, dict) or server not in SERVERS or value.get("schemaVersion") != 1 or value.get("serverId") != server:
        raise ValueError("invalid observation identity")
    for field in ("observedAt", "expiresAt"):
        if not isinstance(value.get(field), str):
            raise ValueError("missing observation timestamp")
        stamp = datetime.fromisoformat(value[field].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("observation timestamps need a timezone")
    if value["expiresAt"] == value["observedAt"] or datetime.fromisoformat(value["expiresAt"].replace("Z", "+00:00")) <= datetime.fromisoformat(value["observedAt"].replace("Z", "+00:00")):
        raise ValueError("invalid observation expiry")
    if not isinstance(value.get("boards"), list):
        raise ValueError("missing boards")
    identities = set()
    event_schedule(value.get('eventSchedule'))
    for board in value["boards"]:
        if not isinstance(board, dict):
            raise ValueError("invalid ranking board")
        identity = (board.get("eventId"), board.get("type"), board.get("musicId", ""))
        if not isinstance(identity[2], str) or (identity[1] == "music" and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identity[2])) or (identity[1] != "music" and identity[2]):
            raise ValueError("invalid music identity")
        if not isinstance(identity[0], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identity[0]) or not isinstance(identity[1], str) or identity[1] not in BOARDS or identity in identities:
            raise ValueError("invalid board identity")
        identities.add(identity)
        if any(key in board and (not isinstance(board[key], str) or len(board[key]) > 500)
               for key in ("eventName", "musicName")):
            raise ValueError("invalid ranking label")
        if not isinstance(board.get("entries"), list):
            raise ValueError("missing ranking entries")
        players = set()
        for row in board["entries"]:
            if not isinstance(row, dict):
                raise ValueError("invalid player result")
            if not isinstance(row.get("playerId"), str) or not row["playerId"] or row["playerId"] in players:
                raise ValueError("invalid player identity")
            if not isinstance(row.get("name"), str) or len(row['name']) > 500 or type(row.get("rank")) is not int or not 1 <= row["rank"] <= (1 << 53) - 1 or type(row.get("score")) is not int or not 0 <= row["score"] <= (1 << 53) - 1:
                raise ValueError("invalid player result")
            players.add(row["playerId"])
            public_high_score_deck(row.get('highScoreDeck'))
            public_player_profile(row.get('profile'))
    return value


def query_player_rankings(root: Path, *, server: str, board: str = "auto", event: str | None = None,
                          music: str = "", cursor: str | None = None, limit: int = 50, now: datetime | None = None) -> dict:
    if server not in SERVERS or board not in BOARDS | {"auto"} or not 1 <= limit <= 100 or (board != "music" and music):
        raise ValueError("invalid query")
    path = root / server / "current.json"
    result = {"schemaVersion": 1, "serverId": server, "board": board, "eventId": event, "musicId": music,
              "status": "unavailable", "observedAt": None, "expiresAt": None, "events": [], "songs": [], "boards": [], "entries": [], "nextCursor": None}
    current_raw = path.read_bytes() if path.exists() else None
    current = validate_observation(json.loads(current_raw), server) if current_raw is not None else None
    current_time = now or datetime.now(timezone.utc)
    current_schedule = event_schedule(current.get('eventSchedule')) if current else None
    current_events = list({b["eventId"]: {"id": b["eventId"], "name": b.get("eventName", b["eventId"])}
                           for b in current["boards"]}.values()) if current else []
    archives = list_final_archives(root, server)
    current_ids = {item["id"] for item in current_events}
    for item in current_events:
        if current_schedule and current_schedule['eventId'] == item['id']:
            item.update(startAt=current_schedule['startAt'], endAt=current_schedule['endAt'],
                        state=schedule_state(current_schedule, current_time))
        if item['id'] in archives:
            item.update(state='ended', isFinal=True)
    result["events"] = current_events + [
        {"id": key, "name": archives[key]["eventName"], "state": "ended", "isFinal": True}
        for key in sorted(archives, key=int, reverse=True) if key not in current_ids]
    event = event or (result["events"][0]["id"] if result["events"] else None)
    result["eventId"] = event
    archived = False
    if event in current_ids and event not in archives:
        raw, data = current_raw, current
    elif event in archives:
        archive_path, _ = final_archive_paths(root, server, event)
        raw = archive_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != archives[event]["sha256"]:
            raise ValueError("final ranking digest mismatch")
        data = validate_observation(json.loads(raw), server)
        metadata = final_archive_metadata(data, server, raw)
        if metadata != archives[event]:
            raise ValueError("final ranking metadata mismatch")
        archived = True
    else:
        return result
    result.update(observedAt=data["observedAt"], expiresAt=data["expiresAt"])
    result["isFinal"] = archived
    selected_schedule = event_schedule(data.get('eventSchedule'))
    result['eventState'] = 'ended' if archived else schedule_state(selected_schedule, current_time)
    if archived:
        result['expiresAt'] = None
    result["boards"] = list(dict.fromkeys(b['type'] for b in data['boards'] if b['eventId'] == event))
    if board == 'auto' and result['boards']:
        board = result['boards'][0]
        result['board'] = board
    result["songs"] = [{"id": str(b.get("musicId", "")), "name": b.get("musicName", str(b.get("musicId", "")))}
                       for b in data["boards"] if b["eventId"] == event and b["type"] == "music"]
    music = music or (result["songs"][0]["id"] if board == "music" and result["songs"] else "")
    result["musicId"] = music
    selected = next((b for b in data["boards"] if b["eventId"] == event and b["type"] == board and str(b.get("musicId", "")) == music), None)
    if selected is None:
        result.update(observedAt=None, expiresAt=None)
        return result
    result['coverage'] = selected.get('coverage')
    result['totalEntries'] = len(selected['entries'])
    identity = [server, event, board, music, hashlib.sha256(raw).hexdigest()]
    offset = 0
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if decoded["identity"] != identity or type(decoded["offset"]) is not int or decoded["offset"] < 0:
                raise ValueError("cursor scope mismatch")
            offset = decoded["offset"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("invalid or expired cursor") from exc
    entries = sorted(selected["entries"], key=lambda r: (r["rank"], r["playerId"]))
    result["entries"] = [{**{key: row[key] for key in ("playerId", "name", "rank", "score")},
                          "playerKey": f"{server}:{row['playerId']}",
                          "profile": public_player_profile(row.get('profile')),
                          "highScoreDeck": public_high_score_deck(row.get('highScoreDeck'))}
                         for row in entries[offset:offset + limit]]
    expired = datetime.fromisoformat(data["expiresAt"].replace("Z", "+00:00")) <= (now or datetime.now(timezone.utc))
    result["status"] = "stale" if expired and not archived else "available" if entries else "empty"
    if offset + limit < len(entries):
        result["nextCursor"] = base64.urlsafe_b64encode(json.dumps({"identity": identity, "offset": offset + limit}).encode()).decode().rstrip("=")
    return result
