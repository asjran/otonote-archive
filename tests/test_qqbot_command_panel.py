import asyncio
import json
from pathlib import Path

import httpx
import pytest

from backend.qqbot.config import Config
from tools import qqbot_command_panel as module


def test_qq_omitted_false_defaults_match_without_duplicate():
    expected = module.panel()
    returned = {'items': [{k: v for k, v in item.items() if k != 'only_admin'} for item in expected['items']]}
    assert module.decide([{'target_type': 'all', 'panel': returned}], expected) == 'unchanged'


def test_other_or_targeted_panels_are_not_overwritten():
    for records in ([{'target_type': 'specific', 'panel': module.panel()}],
                    [{'target_type': 'all', 'panel': {'items': []}}]):
        with pytest.raises(ValueError, match='existing_panels_require_review'):
            module.decide(records, module.panel())


@pytest.mark.parametrize('apply', [False, True])
def test_inspect_and_idempotent_create_against_official_response_shapes(monkeypatch, apply):
    records, mutations = [], []
    def request(req):
        if req.url.path.endswith('getAppAccessToken'):
            return httpx.Response(200, json={'access_token': 'fixture-only', 'expires_in': 7200})
        assert req.url.path == '/v2/panels'
        if req.method == 'GET':
            assert req.url.params['scope'] == 'group'
            return httpx.Response(200, json={'is_end': True, **({'records': records} if records else {})})
        assert req.method == 'POST'
        body = json.loads(req.content)
        assert body['scope'] == 'group' and body['target_type'] == 'all'
        mutations.append(body)
        items = [{k: v for k, v in item.items() if k != 'only_admin'} for item in body['panel']['items']]
        records.append({'panel_id': 'fixture-panel', 'target_type': 'all', 'panel': {'items': items}})
        return httpx.Response(200, json={'panel_id': 'fixture-panel'})
    config = Config('123', 'fixture-only', Path('/unused'), Path('/unused'), 'https://bot.example.com')
    monkeypatch.setattr(module.Config, 'from_env', lambda: config)
    client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: client(transport=httpx.MockTransport(request), **kwargs))
    first = asyncio.run(module.run('group', apply))
    second = asyncio.run(module.run('group', apply))
    assert len(mutations) == (1 if apply else 0)
    if apply:
        assert first['action'] == 'create' and first['verified']
        assert second['action'] == 'unchanged' and second['verified']
    else:
        assert first['action'] == second['action'] == 'preview'
