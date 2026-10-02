import base64
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from tools.resource_pipeline.adapters.jp_public import JpPublicClient, API_ROOT
from tools.resource_pipeline.adapters.global_public import ProtocolError
from tools.resource_pipeline.transport import HttpResponse


class JpTransportTests(unittest.TestCase):
    def setUp(self):
        self.authorization = 'Basic ' + base64.b64encode(b'test-client:test-only').decode()
        self.client = JpPublicClient('1.0.4', self.authorization)

    def test_requires_explicit_valid_authorization(self):
        for value in (None, '', 'Bearer sample', 'Basic broken', self.authorization+'\r\nX-Test: bad'):
            with self.assertRaises(ProtocolError):JpPublicClient('1.0.4', value)

    def test_rpc_is_fixed_read_only_and_credentials_are_not_arguments(self):
        payload = b'\x0a\x03abc'
        def run(command, **options):
            self.assertNotIn(self.authorization, ' '.join(command))
            self.assertIn(self.authorization.encode(), options['input'])
            self.assertEqual(command[-1], API_ROOT+'/app.masterdata.MasterdataService/Version')
            self.assertEqual(Path(command[command.index('--data-binary')+1][1:]).read_bytes(), bytes(5))
            Path(command[command.index('--dump-header')+1]).write_text('HTTP/2 200\r\ncontent-type: application/grpc\r\ngrpc-status: 0\r\nset-cookie: must-not-leak\r\n')
            Path(command[command.index('--output')+1]).write_bytes(b'\x00'+len(payload).to_bytes(4,'big')+payload)
            return Mock(returncode=0)
        with patch('tools.resource_pipeline.adapters.jp_public.subprocess.run',side_effect=run) as call:
            headers, actual = self.client.rpc('app.masterdata.MasterdataService/Version')
            self.assertEqual(actual,payload);self.assertNotIn('set-cookie',headers)
            with self.assertRaises(ProtocolError):self.client.rpc('app.playerlogin.PlayerLoginService/PlayerLogin')
            self.assertEqual(call.call_count,1)

    def test_refusal_stops_without_retry_and_does_not_include_credentials(self):
        def run(command, **options):
            Path(command[command.index('--dump-header')+1]).write_text('HTTP/2 403\r\ncontent-type: application/grpc\r\ngrpc-status: 7\r\n')
            Path(command[command.index('--output')+1]).write_bytes(b'')
            return Mock(returncode=0)
        with patch('tools.resource_pipeline.adapters.jp_public.subprocess.run',side_effect=run) as call:
            with self.assertRaisesRegex(ProtocolError,'HTTP status 403') as error:self.client.rpc('app.masterdata.MasterdataService/Version')
            self.assertNotIn(self.authorization,str(error.exception));self.assertEqual(call.call_count,1)

    def test_static_resources_cannot_forward_credentials_to_another_host(self):
        with patch('tools.resource_pipeline.adapters.jp_public.HttpTransport') as transport:
            transport.return_value.request.return_value=HttpResponse(200,{},b'content')
            self.assertEqual(self.client.get('https://static.bang-dream-on.jp/catalog.hash',256).body,b'content')
            request=transport.return_value.request.call_args.args[0]
            self.assertEqual(request.headers['Authorization'],self.authorization)
            for url in ('https://example.com/catalog.hash','http://static.bang-dream-on.jp/catalog.hash','https://static.bang-dream-on.jp@evil.invalid/catalog.hash'):
                with self.assertRaises(ProtocolError):self.client.get(url,256)
            with self.assertRaises(ProtocolError):self.client.get('https://static.bang-dream-on.jp/',256,method='POST')
            self.assertEqual(transport.return_value.request.call_count,1)




class JpSourceTests(unittest.TestCase):
    def test_jp_versions_and_paths_are_not_global_paths(self):
        from tools.resource_pipeline.adapters.jp_public import asset_directory, asset_url
        version = '1.0.0.300/'+'a'*32
        self.assertEqual(asset_directory(version), 'https://static.bang-dream-on.jp/asset/1.0.0.300/Android/'+'a'*32)
        self.assertTrue(asset_url(version, '{Fwk.Resource.RemoteAssetDir}/cri_assets_cri/sound/test').endswith('/cri_assets_cri/sound/test'))
        for path in ('https://dummy.net/asset/test', '{Fwk.Resource.RemoteAssetDir}/../other', '{Fwk.Resource.RemoteAssetDir}/%2e%2e/other'):
            with self.assertRaises(ProtocolError):asset_url(version, path)
        with self.assertRaises(ProtocolError):asset_directory('1.0.0.300')

    def test_catalog_gzip_is_bounded(self):
        import gzip
        from tools.resource_pipeline.adapters.jp_public import decode_catalog
        self.assertEqual(decode_catalog(gzip.compress(b'catalog')),b'catalog')
        self.assertEqual(decode_catalog(b'catalog'),b'catalog')
        with self.assertRaisesRegex(ProtocolError,'size limit'):decode_catalog(gzip.compress(b'x'*100),limit=10)
        with self.assertRaises(ProtocolError):decode_catalog(b'\x1f\x8bbroken')

    def test_jp_response_uses_header_and_missing_header_fails_closed(self):
        c=JpPublicClient('1.0.4','Basic '+base64.b64encode(b'client:test').decode())
        master='1.0.0.300/'+'a'*32;resource='1.0.0.300/'+'b'*32
        payload=b'\x0a'+bytes([len(master)])+master.encode()
        with patch.object(c,'rpc',return_value=({'x-asset-version':resource},payload)):
            observation=c.discover()
            self.assertEqual(observation['region'],'jp')
            self.assertEqual(observation['resourceVersion'],resource)
            self.assertIn('/1.0.0.300/Android/'+('b'*32),observation['catalogUrl'])
        with patch.object(c,'rpc',return_value=({},payload)):
            with self.assertRaises(ProtocolError):c.discover()
        with patch.object(c,'rpc',return_value=({'x-asset-version':resource,'x-client-recommended-version':'1.0.5'},payload)):
            with self.assertRaisesRegex(ProtocolError,'verified client intake'):c.discover()

    def test_authenticated_requests_never_follow_redirects(self):
        from tools.resource_pipeline.adapters.jp_public import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(None,None,302,'',{},'http://static.bang-dream-on.jp/file'))


class JpIncrementalTests(unittest.TestCase):
    def test_verified_cache_is_reused_across_version_directories_and_corruption_stops(self):
        import hashlib,tempfile
        from tools.jp_remote_sync import acquire
        from tools.resource_pipeline.transport import DownloadReceipt
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cache';body=b'verified resource';identity={'key':'asset','hash':'same','size':len(body)}
            client=Mock()
            def download(url,stream,limit):
                stream.write(body)
                return DownloadReceipt(200,{'etag':hashlib.md5(body).hexdigest()},len(body))
            client.download.side_effect=download
            a=acquire(client,'https://static.bang-dream-on.jp/v1/asset',path,len(body),identity=identity)
            b=acquire(client,'https://static.bang-dream-on.jp/v2/asset',path,len(body),identity=identity)
            self.assertFalse(a['reused']);self.assertTrue(b['reused']);self.assertEqual(client.download.call_count,1)
            with self.assertRaises(ProtocolError):acquire(client,'https://static.bang-dream-on.jp/v3/asset',path,len(body),identity={**identity,'hash':'changed'})
            path.write_bytes(b'x'*len(body))
            with self.assertRaises(ProtocolError):acquire(client,'https://static.bang-dream-on.jp/v2/asset',path,len(body),identity=identity)
            self.assertEqual(client.download.call_count,1)

    def test_failed_download_does_not_commit_bytes_or_receipt(self):
        import tempfile
        from tools.jp_remote_sync import acquire
        from tools.resource_pipeline.transport import DownloadReceipt
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cache';client=Mock()
            def download(url,stream,limit):
                stream.write(b'wrong')
                return DownloadReceipt(200,{},5)
            client.download.side_effect=download
            with self.assertRaises(ProtocolError):acquire(client,'https://static.bang-dream-on.jp/file',path,5,expected_sha='0'*64)
            self.assertFalse(path.exists());self.assertFalse(path.with_name('cache.receipt.json').exists())
            client.download.side_effect=ProtocolError('JP resource HTTP 403')
            with self.assertRaises(ProtocolError):acquire(client,'https://static.bang-dream-on.jp/file',path,5,expected_sha='0'*64)
            self.assertFalse(path.exists());self.assertEqual(client.download.call_count,2)

    def test_unverified_metadata_is_rejected_before_extracting_credentials(self):
        import tempfile
        from tools.jp_remote_sync import client_from_metadata
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'metadata';path.write_bytes(b'untrusted')
            with self.assertRaisesRegex(ProtocolError,'explicit authorization'):client_from_metadata(path)
            with self.assertRaisesRegex(ProtocolError,'unverified JP client'):client_from_metadata(path,authorize_builtin_credentials=True)


if __name__=='__main__':unittest.main()
