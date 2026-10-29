import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('configure_neon',Path(__file__).with_name('configure_neon.py'))
neon=importlib.util.module_from_spec(spec);spec.loader.exec_module(neon)

class NeonConfigTests(unittest.TestCase):
    def test_direct_uri_and_tls_are_enforced(self):
        service,password=neon.service_files('postgresql://owner:example-password@ep-test.aws.neon.tech/annha?sslmode=disable')
        self.assertIn('sslmode=verify-full',service)
        self.assertNotIn('example-password',service)
        self.assertIn(':owner:example-password',password)
    def test_password_is_decoded_and_pgpass_escaped(self):
        _,password=neon.service_files('postgresql://owner:a%3Ab%5Cc%40d@ep-test.aws.neon.tech/annha')
        self.assertTrue(password.endswith(':a\\:b\\\\c@d\n'))
    def test_pooler_other_hosts_and_line_injection_rejected(self):
        for uri in ('postgresql://owner:password@ep-test-pooler.aws.neon.tech/annha','postgresql://owner:password@example.com/annha','postgresql://owner:password@ep-test.aws.neon.tech/annha%0Ahost%3Devil'):
            with self.assertRaises(ValueError): neon.service_files(uri)
    def test_existing_custom_secret_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'.secrets').mkdir();(root/'docker/database').mkdir(parents=True)
            for filename in ('pgpass','pg_service.conf'):
                (root/'docker/database'/f'{filename}.example').write_text('template')
                (root/'.secrets'/filename).write_text('custom-existing-secret')
            with self.assertRaises(ValueError): neon.save_files('postgresql://owner:password@ep-test.aws.neon.tech/annha',root)
            self.assertEqual((root/'.secrets/pgpass').read_text(),'custom-existing-secret')
    def test_placeholders_are_replaced_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'.secrets').mkdir();(root/'docker/database').mkdir(parents=True)
            for filename in ('pgpass','pg_service.conf'):
                (root/'docker/database'/f'{filename}.example').write_text('template')
                (root/'.secrets'/filename).write_text('template')
            neon.save_files('postgresql://owner:password@ep-test.aws.neon.tech/annha',root)
            self.assertIn('sslmode=verify-full',(root/'.secrets/pg_service.conf').read_text())
            self.assertIn(':owner:password',(root/'.secrets/pgpass').read_text())

if __name__=='__main__': unittest.main()
