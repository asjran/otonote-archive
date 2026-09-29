"""Small bounded loopback client: no environment proxy or redirect fallback."""
import json
import urllib.error
import urllib.request

from .config import loopback_url, secret


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(source, path, payload=None, write=False):
    url = loopback_url(source["url"]) + path
    key = source.get("writeTokenEnv") if write else source.get("readTokenEnv")
    headers = {"Authorization": "Bearer " + secret(key), "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=3) as response:
        body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError("response too large")
        return json.loads(body)
