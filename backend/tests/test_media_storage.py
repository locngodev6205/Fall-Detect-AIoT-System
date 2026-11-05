import hashlib
from pathlib import Path
import tempfile
import unittest
import uuid

from backend.src import media_storage, media_migration


class FakeResponse:
    status=206
    def __init__(self, body=b'partial'):
        self.headers={'Content-Length':str(len(body)),'Content-Range':'bytes 0-6/9','Accept-Ranges':'bytes'}
        self.body=body
        self.closed=False
    def read(self,size=-1):
        result,self.body=self.body,b''
        return result
    def close(self): self.closed=True


class FakeSDK:
    def __init__(self,result=None,delete_result=None):
        self.configuration=None
        self.upload_options=None
        self.delete_options=None
        self.url_options=None
        self.result=result
        self.delete_result=delete_result or {'result':'ok'}
        self.root=self
        self.uploader=self
        self.utils=self
    def config(self,**kwargs): self.configuration=kwargs
    def upload(self,path,**kwargs):
        self.upload_options=kwargs
        return self.result
    def destroy(self,public_id,**kwargs):
        self.delete_options=(public_id,kwargs)
        return self.delete_result
    def cloudinary_url(self,public_id,**kwargs):
        self.url_options=kwargs
        return ('https://signed.invalid/private-media',{})


class MediaStorageTests(unittest.TestCase):
    def test_cloudinary_inventory_paginates_and_reports_orphans(self):
        class AdminAPI:
            def __init__(self): self.calls=[]
            def resources(self,**kwargs):
                self.calls.append(kwargs)
                if kwargs['resource_type']=='image' and kwargs['next_cursor'] is None:
                    return {'resources':[{'public_id':'annha/development/known','resource_type':'image',
                        'type':'authenticated','asset_id':'asset-known'}],'next_cursor':'next'}
                if kwargs['resource_type']=='image':
                    return {'resources':[{'public_id':'annha/development/orphan','resource_type':'image',
                        'type':'authenticated','asset_id':'asset-orphan'}]}
                return {'resources':[]}
        provider=media_storage.CloudinaryStorage({'CLOUDINARY_CLOUD_NAME':'test',
            'CLOUDINARY_API_KEY':'key','CLOUDINARY_API_SECRET':'secret'},sdk=FakeSDK())
        admin=AdminAPI()
        result=media_migration.cloudinary_inventory(provider,
            {('annha/development/known','image','authenticated','asset-known')},admin)
        self.assertEqual(result['cloud_inventory_status'],'complete')
        self.assertEqual(result['cloud_provider_assets'],2)
        self.assertEqual(result['cloudinary_orphans'],1)
        self.assertEqual(result['cloud_metadata_missing_from_inventory'],0)
        self.assertEqual(len(admin.calls),4)
        self.assertTrue(all(call['prefix']=='annha/development/' for call in admin.calls))

    def test_secret_parser_keeps_folder_with_spaces(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'cloudinary.env'
            path.write_text('CLOUDINARY_CLOUD_NAME=test\nCLOUDINARY_API_KEY=key\nCLOUDINARY_API_SECRET=secret\nCLOUDINARY_ASSET_FOLDER=Fall Detection\n')
            config=media_storage.parse_config(path,environ={})
            self.assertEqual(config['CLOUDINARY_ASSET_FOLDER'],'Fall Detection')
            self.assertTrue(media_storage.cloudinary_configured(path,environ={}))

    def test_signed_private_upload_uses_server_id_and_folder(self):
        media_id=str(uuid.uuid4());data=b'PNG fixture';digest=hashlib.sha256(data).digest()
        sdk=FakeSDK({'type':'authenticated','public_id':f'annha/development/{media_id}',
            'resource_type':'image','bytes':len(data),'asset_id':'provider-asset','version':17,
            'width':1,'height':1})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'upload.png';path.write_bytes(data)
            storage=media_storage.CloudinaryStorage({'CLOUDINARY_CLOUD_NAME':'test',
                'CLOUDINARY_API_KEY':'key','CLOUDINARY_API_SECRET':'secret',
                'CLOUDINARY_ASSET_FOLDER':'Fall Detection'},sdk=sdk)
            asset=storage.upload(path,media_id,'image/png')
        self.assertEqual(asset.provider,'cloudinary')
        self.assertEqual(asset.sha256,digest)
        self.assertEqual(sdk.upload_options['type'],'authenticated')
        self.assertEqual(sdk.upload_options['asset_folder'],'Fall Detection')
        self.assertEqual(sdk.upload_options['public_id'],f'annha/development/{media_id}')
        self.assertTrue(sdk.upload_options['overwrite'])
        self.assertNotIn('api_secret',sdk.upload_options)

    def test_audio_dimensions_reported_as_zero_are_stored_as_absent(self):
        media_id=str(uuid.uuid4());data=b'RIFF'+(36).to_bytes(4,'little')+b'WAVEfmt '+b'\x00'*32
        sdk=FakeSDK({'type':'authenticated','public_id':f'annha/development/{media_id}',
            'resource_type':'video','bytes':len(data),'asset_id':'provider-audio','version':8,
            'width':0,'height':0,'duration':0.1})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'upload.wav';path.write_bytes(data)
            storage=media_storage.CloudinaryStorage({'CLOUDINARY_CLOUD_NAME':'test',
                'CLOUDINARY_API_KEY':'key','CLOUDINARY_API_SECRET':'secret'},sdk=sdk)
            asset=storage.upload(path,media_id,'audio/wav')
        self.assertEqual(asset.resource_type,'video')
        self.assertIsNone(asset.width);self.assertIsNone(asset.height)

    def test_mp3_uses_authenticated_video_resource_and_mp3_delivery_format(self):
        media_id=str(uuid.uuid4());data=(bytes.fromhex('fffb9000')+bytes(413))*5
        sdk=FakeSDK({'type':'authenticated','public_id':f'annha/development/{media_id}',
            'resource_type':'video','bytes':len(data),'asset_id':'provider-mp3','version':12,
            'duration':0.13})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'upload.mp3';path.write_bytes(data)
            storage=media_storage.CloudinaryStorage({'CLOUDINARY_CLOUD_NAME':'test',
                'CLOUDINARY_API_KEY':'key','CLOUDINARY_API_SECRET':'secret'},sdk=sdk)
            asset=storage.upload(path,media_id,'audio/mpeg')
            row={'public_id':asset.public_id,'resource_type':asset.resource_type,
                'delivery_type':asset.delivery_type,'provider_version':asset.provider_version,
                'mime_type':'audio/mpeg'}
            storage.signed_url(row)
        self.assertEqual(asset.resource_type,'video')
        self.assertEqual(sdk.upload_options['resource_type'],'video')
        self.assertEqual(sdk.url_options['format'],'mp3')

    def test_private_read_forwards_range_without_returning_signed_url(self):
        sdk=FakeSDK()
        requests=[]
        def opener(request,timeout):
            requests.append(request)
            return FakeResponse()
        storage=media_storage.CloudinaryStorage({'CLOUDINARY_CLOUD_NAME':'test',
            'CLOUDINARY_API_KEY':'key','CLOUDINARY_API_SECRET':'secret'},sdk=sdk,opener=opener)
        row={'public_id':'annha/development/id','resource_type':'video','delivery_type':'authenticated',
             'provider_version':4,'mime_type':'audio/wav'}
        response=storage.open_read(row,'bytes=0-6')
        self.assertEqual(requests[0].get_header('Range'),'bytes=0-6')
        self.assertEqual(response.status,206)
        self.assertEqual(sdk.url_options['format'],'wav')
        self.assertNotIn('signed.invalid',repr(row))
        response.close()

    def test_destroy_is_idempotent_for_missing_provider_asset(self):
        sdk=FakeSDK(delete_result={'result':'not found'})
        storage=media_storage.CloudinaryStorage({'CLOUDINARY_CLOUD_NAME':'test',
            'CLOUDINARY_API_KEY':'key','CLOUDINARY_API_SECRET':'secret'},sdk=sdk)
        storage.delete({'public_id':'annha/development/id','resource_type':'image'})
        self.assertEqual(sdk.delete_options[1]['type'],'authenticated')
        self.assertTrue(sdk.delete_options[1]['invalidate'])

    def test_local_path_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            storage=media_storage.LocalStorage(folder)
            with self.assertRaises(media_storage.MediaNotFound):
                storage.path_for({'local_object_key':'../secret'})


if __name__=='__main__':
    unittest.main()
