"""Inspect or initialize an empty QQ command panel; never overwrite existing panels.

Run with the bot's environment, e.g. pipe into docker exec python - --apply.
Default is read-only. QQ messages are never sent by this administrative tool.
Official API: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/menu-panel/
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone

import httpx

from backend.qqbot.config import Config
from backend.qqbot.transport import QQClient, QQError


COMMANDS = (
    ('帮助', '查看全部指令与查询示例'),
    ('查角色卡', '查询卡面、属性和技能'),
    ('查留影', '查询留影与支援技能'),
    ('查歌曲', '查询歌曲与谱面难度'),
    ('查卡池', '查询招募时间与UP角色卡'),
    ('查角色', '查询人物档案与关联资料'),
)


def panel():
    return {'items': [{'type': 'command', 'name': name, 'desc': desc, 'only_admin': False}
                      for name, desc in COMMANDS], 'remark': 'Our Notes 国际服资料查询'}


def decide(records, expected):
    """Avoid duplicate creation and preserve configurations managed elsewhere."""
    def normalized(items):
        # The official response omits only_admin=false (protobuf default).
        return [{**item, 'only_admin': item.get('only_admin', False)} for item in items]

    for row in records:
        items = row.get('panel', {}).get('items', [])
        if row.get('target_type') == 'all' and normalized(items) == normalized(expected['items']):
            return 'unchanged'
    if records:
        raise ValueError('existing_panels_require_review')
    return 'create'


async def run(scope, apply):
    config = Config.from_env()
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
        client = QQClient(config.app_id, config.secret, http, config.api_base_url)
        token = await client.access_token()
        headers = {'Authorization': 'QQBot ' + token}

        async def request(method, path, **kwargs):
            response = await http.request(method, config.api_base_url + path, headers=headers, **kwargs)
            if not response.is_success:
                raise QQError(f'panel_http_{response.status_code}')
            data = response.json()
            code = data.get('code', data.get('err_code', 0))
            if code not in (None, 0, '0'):
                raise QQError('panel_api_' + (str(code) if str(code).isdigit() else 'unknown'))
            return data

        async def listing():
            records, cursor, seen = [], None, set()
            while True:
                params = {'scope': scope, 'limit': 50}
                if cursor:
                    params['cursor'] = cursor
                data = await request('GET', '/v2/panels', params=params)
                # QQ omits records for an empty last page.
                batch = data.get('records', [] if data.get('is_end') is True else None)
                if not isinstance(batch, list):
                    raise ValueError('invalid_panel_listing')
                records.extend(batch)
                cursor = data.get('next_cursor')
                if data.get('is_end') is True or not cursor:
                    return records
                if cursor in seen or len(seen) >= 20:
                    raise ValueError('invalid_panel_pagination')
                seen.add(cursor)

        before = await listing()
        expected = panel()
        action = decide(before, expected)
        result = {'recordedAt': datetime.now(timezone.utc).isoformat(), 'scope': scope,
                  'beforeCount': len(before), 'action': action if apply else 'preview',
                  'desired': {'scope': scope, 'target_type': 'all', 'panel': expected},
                  'realQQMessagesSent': 0}
        if apply and action == 'create':
            # No automatic POST retry: inspect state before retrying ambiguous failures.
            created = await request('POST', '/v2/panels', json=result['desired'])
            identifier = created.get('panel_id')
            if not identifier:
                raise ValueError('missing_panel_id_inspect_before_retry')
            result['panel_id'] = identifier
        if apply:
            after = await listing()
            if decide(after, expected) != 'unchanged':
                raise ValueError('panel_readback_mismatch')
            result['verified'] = True
            result['after'] = [{k: row.get(k) for k in ('panel_id', 'scope', 'target_type', 'panel', 'version')}
                               for row in after]
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('group', 'c2c'), default='group')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.scope, args.apply))
    except (QQError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
    except httpx.HTTPError:
        raise SystemExit('panel_transport_failure_inspect_before_retry') from None
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
