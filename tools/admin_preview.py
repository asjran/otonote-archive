"""A loopback, read-only dashboard with explicitly synthetic local data."""
import argparse
import datetime as dt
import math
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

from backend.admin.app import create_admin
from backend.admin.store import Store


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=18080)
    args = p.parse_args()
    import uvicorn
    with tempfile.TemporaryDirectory(prefix='ournotes-admin-preview-') as temp:
        store = Store(temp + '/preview.sqlite')
        site = {'id':'preview','name':'Our Notes · 本地演示数据','timezone':'Asia/Shanghai','source':'preview','nodes':['resources']}
        now = time.time()
        store.set_state('started:preview',now - 86400 * 6)
        for i in range(126):
            timestamp = now - (125 - i) * 3700
            path = ['/', '/global/zh-CN/music/', '/global/zh-CN/tools/live2d/', '/global/zh-CN/immersive/'][i % 4]
            store.add_event({'site':'preview','id':str(i).zfill(32),'type':'page_view','path':path,'visitor':str(i//3).zfill(32),'referrer':['direct','search.example','internal'][i%3]}, 'Asia/Shanghai', timestamp)
            if i % 3 == 0:
                store.add_event({'site':'preview','id':'d'+str(i).zfill(31),'type':'download_click','path':path,'resource':['live2d:1001','scene:10001:png','/audio/song.m4a'][i%3]},'Asia/Shanghai',timestamp)
        config = {'schemaVersion':1,'role':'admin','port':args.port,'origin':f'http://127.0.0.1:{args.port}',
                  'auth':{'mode':'preview'},'sites':[site],
                  'sources':[{'id':'preview','url':'http://127.0.0.1:18081'}],
                  'nodes':[{'id':'resources','name':'资源节点 · 本地演示','url':'http://127.0.0.1:18082'}]}
        def transport(source,path,*unused):
            query = parse_qs(urlsplit(path).query)
            if path.startswith('/summary/'):
                return store.summary(site,query.get('window',['today'])[0])
            if path.startswith('/loads'):
                end=time.time();seconds=int(query.get('seconds',['3600'])[0]);step=max(5,seconds//240)
                points=[]
                for index in range(240):
                    ts=end-(239-index)*step
                    missing=105<index<115
                    tx=2.4+math.sin(index/16)*.8+math.sin(index/5)*.25
                    rx=.3+math.sin(index/21)*.1
                    points.append({'ts':ts,'active':None if missing else round(34+math.sin(index/20)*8),
                                   'reading':1,'writing':9,'waiting':24,'rps':None if missing else 12+math.sin(index/14)*4,
                                   'txMbps':None if missing else tx,'rxMbps':None if missing else rx,
                                   'txBytes':None if missing else tx*1e6/8*step,'rxBytes':None if missing else rx*1e6/8*step,
                                   'txLimitMbps':10,'rxLimitMbps':None,'gap':missing,'elapsed':step})
                return {'sources':[{'source':'demo','name':'模拟 Nginx / 模拟网卡','resolution':step,'latest':points[-1],'points':points}]}
            if path=='/state':
                return {'profiles':[{'id':'global','name':'Global 资源','status':'passed','steps':[{'name':'resource-version','status':'passed'}]}],
                        'tasks':[{'id':'preview-task','profile':'global','status':'succeeded','message':'演示：版本检查完成，未执行真实操作','updated':now}]}
            raise ValueError('unsupported preview request')
        try:
            uvicorn.run(create_admin(config,transport),host='127.0.0.1',port=args.port,access_log=False,proxy_headers=False)
        finally:
            store.close()


if __name__=='__main__':main()
