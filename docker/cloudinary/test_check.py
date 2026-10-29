import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('cloud_check', Path(__file__).with_name('check.py'))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

class CloudCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'cloudinary.env'
        self.path.write_text('CLOUDINARY_CLOUD_NAME=test-cloud\nCLOUDINARY_API_KEY=test-key\nCLOUDINARY_API_SECRET=secret-never-log\nCLOUDINARY_UPLOAD_PRESET=annha_private\nCLOUDINARY_DELIVERY_TYPE=authenticated\nCLOUDINARY_MAX_FILE_BYTES=26214400\n')
    def tearDown(self):
        self.temp.cleanup()
    def test_local_validation_does_not_connect_or_log_credentials(self):
        output = io.StringIO()
        with patch.object(check, 'get_admin') as remote, contextlib.redirect_stdout(output):
            self.assertEqual(check.main(['--config',str(self.path),'--validate-only']),0)
            remote.assert_not_called()
        self.assertNotIn('secret-never-log',output.getvalue())
    def test_placeholder_rejected_without_secret_logging(self):
        self.path.write_text(self.path.read_text().replace('test-cloud','REPLACE_CLOUD_NAME'))
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(check.main(['--config',str(self.path)]),1)
        self.assertNotIn('secret-never-log',output.getvalue())
    def test_unsafe_cloud_path_and_public_type_rejected(self):
        for value in ['../another','test-cloud/path']:
            self.path.write_text(self.path.read_text().replace('test-cloud',value))
            with self.assertRaises(ValueError): check.load_config(self.path)
            self.path.write_text(self.path.read_text().replace(value,'test-cloud'))
        self.path.write_text(self.path.read_text().replace('authenticated','upload'))
        with self.assertRaises(ValueError): check.load_config(self.path)
    def test_unsigned_preset_rejected(self):
        with patch.object(check,'get_admin',side_effect=[{'status':'ok'},{'unsigned':True,'settings':{'type':'authenticated'}}]), contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check.main(['--config',str(self.path),'--check-preset']),1)
    def test_public_delivery_preset_rejected(self):
        with patch.object(check,'get_admin',side_effect=[{'status':'ok'},{'unsigned':False,'settings':{'type':'upload'}}]),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check.main(['--config',str(self.path),'--check-preset']),1)
    def test_signed_authenticated_preset_accepted(self):
        with patch.object(check,'get_admin',side_effect=[{'status':'ok'},{'unsigned':False,'settings':{'type':'authenticated'}}]),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check.main(['--config',str(self.path),'--check-preset']),0)

    def test_setup_keeps_existing_secure_preset(self):
        with patch.object(check,'get_admin',return_value={'unsigned':False,'settings':{'type':'authenticated'}}) as remote,contextlib.redirect_stdout(io.StringIO()):
            check.setup_preset(check.load_config(self.path))
            self.assertEqual(remote.call_count,1)
    def test_setup_does_not_overwrite_insecure_preset(self):
        with patch.object(check,'get_admin',return_value={'unsigned':True,'settings':{'type':'upload'}}) as remote:
            with self.assertRaises(ValueError): check.setup_preset(check.load_config(self.path))
            self.assertEqual(remote.call_count,1)
    def test_setup_creates_only_when_missing(self):
        absent=check.urllib.error.HTTPError('https://api.cloudinary.com',404,'missing',{},None)
        with patch.object(check,'get_admin',side_effect=[absent,{}, {'unsigned':False,'settings':{'type':'authenticated'}}]) as remote,contextlib.redirect_stdout(io.StringIO()):
            check.setup_preset(check.load_config(self.path))
            self.assertEqual(remote.call_count,3)
            self.assertEqual(remote.call_args_list[1].kwargs['data']['overwrite'],'false')

if __name__ == '__main__': unittest.main()
