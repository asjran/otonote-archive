"""Private dashboard BFF. Credentials and machine endpoints stay on the server."""
import hmac
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .collector import small_json
from .config import secret, validate_config
from .transport import request_json

STATIC = Path(__file__).parent / 'static'


def create_admin(config, transport=request_json):
    c = validate_config(config, 'admin')
    preview = c['auth']['mode'] == 'preview'
    proxy_key = None if preview else secret(c['auth']['proxyTokenEnv'])
    if not preview and not c['auth'].get('users'):
        raise ValueError('an explicit administrator allowlist is required')
    sources = {s['id']: s for s in c.get('sources', [])}
    nodes = {n['id']: n for n in c.get('nodes', [])}
    sites = {s['id']: s for s in c.get('sites', [])}
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def boundary(request, call_next):
        if request.headers.get('host') != urlsplit(c['origin']).netloc:
            return JSONResponse({'error': 'host_not_allowed'}, status_code=403)
        actor = 'local-preview'
        if not preview:
            actor = request.headers.get('x-admin-user', '')
            if not hmac.compare_digest(request.headers.get('x-admin-proxy', ''), proxy_key) or actor not in c['auth']['users']:
                return JSONResponse({'error': 'administrator_authentication_required'}, status_code=401)
        request.state.actor = actor
        if request.method not in {'GET', 'HEAD'}:
            if preview:
                return JSONResponse({'error': 'preview_is_read_only'}, status_code=403)
            if request.headers.get('origin') != c['origin'] or request.headers.get('x-ournotes-request') != '1':
                return JSONResponse({'error': 'request_origin_not_allowed'}, status_code=403)
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
                                 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @app.get('/')
    def index():
        return FileResponse(STATIC / 'index.html')

    @app.get('/assets/{name}')
    def asset(name: str):
        if name not in {'admin.css', 'admin.mjs'}:
            raise HTTPException(404)
        return FileResponse(STATIC / name, media_type='text/javascript' if name.endswith('mjs') else 'text/css')

    @app.get('/api/config')
    def public_config():
        return {'preview': preview, 'sites': [{k: s[k] for k in ('id', 'name', 'timezone', 'nodes') if k in s} for s in sites.values()],
                'nodes': [{'id': n['id'], 'name': n.get('name', n['id']), 'writable': bool(n.get('writeTokenEnv')) and not preview} for n in nodes.values()],
                'connection': 'SSH 本地端口转发', 'sampleSeconds': c['sampleSeconds']}

    @app.get('/api/summary/{site_id}')
    def summary(site_id: str, window: str = 'today'):
        if site_id not in sites or window not in {'today', '7d', '30d', 'month'}:
            raise HTTPException(400, 'unknown site or window')
        try:
            result = transport(sources[sites[site_id]['source']], '/summary/' + quote(site_id) + '?window=' + window)
            return {'status': 'ok', 'data': result, 'fetchedAt': time.time()}
        except (OSError, ValueError):
            return {'status': 'unavailable', 'data': None, 'fetchedAt': time.time()}

    @app.get('/api/loads/{site_id}')
    def loads(site_id: str, seconds: int = 3600):
        if site_id not in sites or seconds not in {900, 3600, 86400}:
            raise HTTPException(400, 'unknown site or window')
        try:
            data = transport(sources[sites[site_id]['source']], '/loads?seconds=' + str(seconds))
            return {'status': 'ok', 'data': data}
        except (OSError, ValueError):
            return {'status': 'unavailable', 'data': None}

    @app.get('/api/nodes/{node_id}')
    def node_state(node_id: str):
        if node_id not in nodes:
            raise HTTPException(404)
        try:
            return {'status': 'ok', 'data': transport(nodes[node_id], '/state')}
        except (OSError, ValueError):
            return {'status': 'unavailable', 'data': None}

    @app.post('/api/nodes/{node_id}/tasks')
    async def submit(node_id: str, request: Request):
        if node_id not in nodes or not nodes[node_id].get('writeTokenEnv'):
            raise HTTPException(403, 'node is read only')
        data = await small_json(request)
        if set(data) != {'profile', 'action', 'key'} or any(not isinstance(v, str) for v in data.values()):
            raise HTTPException(400, 'invalid task')
        if data['action'] != 'check' or data['profile'] not in nodes[node_id].get('profiles', []):
            raise HTTPException(403, 'capability not allowed')
        from starlette.concurrency import run_in_threadpool
        try:
            return await run_in_threadpool(transport, nodes[node_id], '/tasks', {**data, 'actor': request.state.actor}, True)
        except (OSError, ValueError):
            # A timeout is an unknown submission outcome, never an invitation to duplicate it.
            raise HTTPException(503, 'submission_unknown_check_task_list')
    return app
