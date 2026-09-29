"""Read-only loopback preview of independently built code and content stores."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
import json


def handler(code, content):
    code, content = Path(code).resolve(), Path(content).resolve()
    identity = json.loads((code/'code-release.json').read_text())['codeId']
    class Preview(SimpleHTTPRequestHandler):
        def translate_path(self, path):
            path = unquote(urlsplit(path).path)
            if path.startswith('/content/'):
                root, name = content, path[len('/content/'):]
            elif path.startswith('/app/releases/'+identity+'/'):
                root, name = code/'compiled',path[len('/app/releases/'+identity+'/'):]
            elif path.startswith(('/global/zh-CN/','/global/en/')):
                name = path.split('/',3)[3]
                if name.startswith(('vendor/','brand/','images/')) or name == 'favicon.svg': root = code/'compiled'
                elif '.' not in name.rsplit('/',1)[-1]: root,name = code,'index.html'
                else: root,name = code,'.missing'
            elif path == '/': root,name=code,'index.html'
            else: root,name=code,'.missing'
            target=(root/name).resolve()
            if root not in target.parents or any(p.startswith('.') for p in Path(name).parts): return str(code/'.missing')
            return str(target)
        def end_headers(self):
            self.send_header('Cache-Control','no-store')
            super().end_headers()
        def list_directory(self, path):
            self.send_error(404); return None
    return Preview


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code',type=Path,required=True);parser.add_argument('--content',type=Path,required=True)
    parser.add_argument('--port',type=int,default=4321)
    args=parser.parse_args()
    ThreadingHTTPServer(('127.0.0.1',args.port),handler(args.code,args.content)).serve_forever()
