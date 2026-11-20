"""OTA regressions: permissions, signed catalog and cancellation/claim ordering."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.src import db, device_updates as updates
from backend.src.device_releases import ReleaseCatalog
from fall_detect.update.updater import extract_bundle, Updater, atomic_json


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / 'test.sqlite3'
        db.initialize()
        updates.initialize()
        with db.connect() as conn:
            conn.execute("INSERT INTO users(id,name,email,password,verified,created_at) VALUES('owner','Owner','owner@test','hash',1,'now')")
            conn.execute("INSERT INTO users(id,name,email,password,verified,created_at) VALUES('other','Other','other@test','hash',1,'now')")
            conn.execute("INSERT INTO homes(id,name,timezone) VALUES('home','Home','UTC')")
            conn.execute("INSERT INTO memberships(home_id,user_id,role) VALUES('home','owner','owner')")
            conn.execute("INSERT INTO cameras(id,home_id,name,token_hash,claimed) VALUES('camera','home','Cam','token',1)")
        app = FastAPI()
        app.include_router(updates.router)
        app.dependency_overrides[updates.security.user] = lambda: {'id': 'owner'}
        app.dependency_overrides[updates.security.device] = lambda: {'id': 'camera', 'home_id': 'home'}
        self.app = app
        self.client = TestClient(app)
        self.old_releases = updates.catalog.releases
        self.manifest = {'version': '1.0.0', 'target': 'linux-arm64', 'commit': 'a' * 40,
            'runtime_sha256': 'b' * 64, 'model_sha256': 'c' * 64, 'sha256': 'd' * 64, 'bytes': 100}
        updates.catalog.releases = {'1.0.0': {'manifest': self.manifest, 'manifest64': '', 'signature': '', 'notes': ''}}
        self.client.post('/api/device/updates/heartbeat', json={**{k: self.manifest[k] for k in ('target', 'runtime_sha256', 'model_sha256')}, 'current_version': '0.0.0', 'previous_version': None, 'ready': True})

    def tearDown(self):
        self.client.close()
        updates.catalog.releases = self.old_releases
        db.DB_PATH = self.old_db
        self.tmp.cleanup()

    def create(self, **body):
        return self.client.post('/api/cameras/camera/updates', json={'version': '1.0.0', **body})

    def report(self, job, status):
        return self.client.post(f'/api/device/updates/{job}/progress', json={'status': status})

    def test_release_visible_owner_only_and_single_job(self):
        self.assertEqual(self.client.get('/api/cameras/camera/updates').json()['releases'][0]['version'], '1.0.0')
        self.assertEqual(self.create().status_code, 200)
        self.assertEqual(self.create().status_code, 409)
        self.app.dependency_overrides[updates.security.user] = lambda: {'id': 'other'}
        self.assertEqual(self.client.get('/api/cameras/camera/updates').status_code, 404)
        self.assertEqual(self.create().status_code, 404)
        self.app.dependency_overrides[updates.security.user] = lambda: {'id': 'owner'}
        with db.connect() as conn:
            conn.execute("UPDATE memberships SET role='caregiver' WHERE user_id='owner'")
            conn.execute("INSERT INTO camera_grants(home_id,camera_id,user_id,can_view) VALUES('home','camera','owner',1)")
        self.assertEqual(self.client.get('/api/cameras/camera/updates').status_code, 403)

    def test_cancel_prevents_late_install(self):
        job = self.create().json()['id']
        self.assertEqual(self.report(job, 'downloading').status_code, 200)
        self.assertEqual(self.report(job, 'ready').status_code, 200)
        self.assertEqual(self.client.post(f'/api/cameras/camera/updates/{job}/cancel').status_code, 200)
        self.assertEqual(self.report(job, 'installing').status_code, 409)

    def test_claim_prevents_cancel_and_requires_healthy_state(self):
        job = self.create().json()['id']
        self.report(job, 'downloading')
        self.report(job, 'ready')
        with patch.object(updates, 'blocked', return_value=True):
            self.assertEqual(self.report(job, 'installing').status_code, 409)
        self.assertEqual(self.report(job, 'installing').status_code, 200)
        self.assertEqual(self.client.post(f'/api/cameras/camera/updates/{job}/cancel').status_code, 409)
        self.assertEqual(self.report(job, 'succeeded').status_code, 409)
        self.assertEqual(self.report(job, 'health_check').status_code, 200)
        self.assertEqual(self.report(job, 'rolling_back').status_code, 200)
        self.assertEqual(self.report(job, 'rolling_back').status_code, 200)
        self.assertEqual(self.report(job, 'rolled_back').status_code, 200)

    def test_schedule_expiry_and_incompatible_runtime(self):
        response = self.create(scheduled_at=time.time() + 60)
        job = response.json()['id']
        self.report(job, 'downloading')
        self.report(job, 'ready')
        self.assertEqual(self.report(job, 'installing').status_code, 409)
        with updates.transaction('camera') as conn:
            item = updates.jobs(conn, 'camera')[0]
            item['expires_at'] = time.time() - 1
            updates.save(conn, item)
        self.assertIsNone(self.client.get('/api/device/updates/job').json()['job'])
        updates.catalog.releases['1.0.0']['manifest']['runtime_sha256'] = 'e' * 64
        self.assertEqual(self.create().status_code, 409)


class SignedCatalogTests(unittest.TestCase):
    def test_valid_asset_and_tampered_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Ed25519PrivateKey.generate()
            public = private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
            bundle = b'verified bundle'
            manifest = {'version': '1.0.0', 'target': 'linux-arm64', 'commit': 'a' * 40, 'bytes': len(bundle),
                'sha256': hashlib.sha256(bundle).hexdigest(), 'runtime_sha256': 'b' * 64, 'model_sha256': 'c' * 64}
            raw = json.dumps(manifest).encode()
            assets = {'1': raw, '2': private.sign(raw), '3': bundle}
            listing = [{'tag_name': 'annha-pi-v1.0.0', 'draft': False, 'prerelease': False, 'body': '',
                'assets': [{'id': 1, 'name': 'manifest.json'}, {'id': 2, 'name': 'manifest.sig'}, {'id': 3, 'name': 'annha-pi.tar.gz'}]}]
            def download(url, limit, token, binary=True):
                if 'per_page' in url:
                    self.assertFalse(binary, 'Release listing requires GitHub JSON Accept header')
                    return json.dumps(listing).encode()
                return assets[url.rsplit('/', 1)[1]]
            with patch.dict(os.environ, {'DEVICE_RELEASE_REPO': 'owner/repo', 'DEVICE_RELEASE_PUBLIC_KEY': public, 'DEVICE_RELEASE_CACHE_DIR': tmp}), patch('backend.src.device_releases.download', side_effect=download):
                catalog = ReleaseCatalog()
                catalog.sync()
                self.assertEqual(catalog.public()[0]['version'], '1.0.0')
                self.assertEqual(catalog.bundle(catalog.releases['1.0.0']).read_bytes(), bundle)
                assets['2'] = b'bad-signature'
                catalog.sync()
                self.assertEqual(catalog.public(), [])
                self.assertIn('xác minh', catalog.error)

    def test_archive_rejects_path_escape_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, kind in (('../escaped', tarfile.REGTYPE), ('linked', tarfile.SYMTYPE)):
                path = root / 'test.tar.gz'
                with tarfile.open(path, 'w:gz') as archive:
                    info = tarfile.TarInfo(name)
                    info.type = kind
                    info.linkname = '/etc/passwd'
                    archive.addfile(info)
                with self.assertRaises(ValueError):
                    extract_bundle(path, root / 'out')
            self.assertFalse((root.parent / 'escaped').exists())


class RecoveryTests(unittest.TestCase):
    def test_durable_outcome_retries_report_without_switching(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'shared').mkdir()
            (root / 'shared/updater.json').write_text(json.dumps({'backend_url': 'http://localhost', 'device_token': 'test'}))
            updater = Updater(root)
            journal = {'job': {'id': 'job'}, 'old': '0.0.0', 'outcome': 'succeeded'}
            atomic_json(updater.journal, journal)
            with patch.object(updater, 'report', side_effect=OSError):
                with self.assertRaises(OSError):
                    updater.recover()
            self.assertTrue(updater.journal.exists())
            with patch.object(updater, 'report') as report, patch.object(updater, 'switch') as switch:
                updater.recover()
                report.assert_called_once()
                switch.assert_not_called()
            self.assertFalse(updater.journal.exists())
            updater.lock.close()


class LocalReadinessTests(unittest.TestCase):
    def test_readiness_requires_real_frames_and_idle_audio(self):
        from types import SimpleNamespace
        import threading
        from fall_detect.edge.update_status import UpdateStatusServer
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'requirements.txt').write_text('runtime')
            runtime = SimpleNamespace(force_mock_hardware=False, last_camera_frame=0, last_safety_check=time.monotonic(),
                model_inference_ok=True, local_danger=False, unreported_alert=False,
                maintenance_until=0, update_lock=threading.RLock(), audio=SimpleNamespace(is_busy=lambda: False))
            status = UpdateStatusServer(runtime, root)
            self.assertFalse(status.status()['healthy'])
            runtime.last_camera_frame = time.monotonic()
            self.assertTrue(status.status()['ready'])
            for attribute, invalid in (
                ('last_camera_frame', time.monotonic()-6), ('model_inference_ok', False),
                ('last_safety_check', time.monotonic()-6), ('last_safety_check', 0),
                ('force_mock_hardware', True),
            ):
                with self.subTest(attribute=attribute, invalid=invalid), patch.object(runtime, attribute, invalid):
                    self.assertFalse(status.status()['healthy'])
                    self.assertFalse(status.status()['ready'])
            runtime.last_safety_check = time.monotonic()
            self.assertTrue(status.status()['healthy'])
            runtime.audio.is_busy = lambda: True
            self.assertTrue(status.status()['healthy'])
            self.assertFalse(status.status()['ready'])
            runtime.audio.is_busy = lambda: False
            runtime.unreported_alert = True
            self.assertTrue(status.status()['healthy'])
            self.assertFalse(status.status()['ready'])

    def test_interrupted_install_restores_old_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'shared').mkdir()
            (root / 'shared/updater.json').write_text(json.dumps({'backend_url': 'http://localhost', 'device_token': 'test'}))
            updater = Updater(root)
            journal = {'job': {'id': 'job'}, 'old': '0.0.0'}
            atomic_json(updater.journal, journal)
            with patch.object(updater, 'request', return_value={'job': {'id': 'job', 'status': 'installing'}}), patch.object(updater, 'report') as report, patch.object(updater, 'service') as service, patch.object(updater, 'switch') as switch, patch.object(updater, 'healthy', return_value=True):
                updater.recover()
                switch.assert_called_once_with('0.0.0')
                self.assertEqual(service.call_count, 2)
                self.assertEqual(report.call_args_list[-1].args[1], 'rolled_back')
            self.assertFalse(updater.journal.exists())
            updater.lock.close()


class TransportTests(unittest.TestCase):
    def test_backend_transport(self):
        from fall_detect.update.updater import validate_backend_url
        for url in ('http://localhost:8188', 'http://192.168.1.2:8188',
                    'http://[::1]', 'http://100.64.1.2', 'https://example.com'):
            self.assertEqual(validate_backend_url(url), url)
        for url in ('http://example.com', 'http://8.8.8.8', 'https://user:pass@example.com',
                    'https://example.com?q=secret'):
            with self.assertRaises(ValueError):
                validate_backend_url(url)

    def test_retry_transient_errors_but_not_rejected_claim(self):
        from urllib.error import HTTPError
        from fall_detect.update.updater import TemporaryNetworkError
        updater = object.__new__(Updater)
        throttle = HTTPError('https://example.com', 429, '', {}, None)
        with patch.object(updater, 'request_once', side_effect=[TimeoutError(), throttle, {}]), patch('fall_detect.update.updater.time.sleep') as sleep:
            self.assertEqual(updater.request('job'), {})
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])
        rejected = HTTPError('https://example.com', 409, '', {}, None)
        with patch.object(updater, 'request_once', side_effect=rejected) as request:
            with self.assertRaises(HTTPError):
                updater.request('job')
            request.assert_called_once()
        with patch.object(updater, 'request_once', side_effect=ConnectionResetError), patch('fall_detect.update.updater.time.sleep'):
            with self.assertRaises(TemporaryNetworkError):
                updater.request('job')

    def test_parallel_claims_do_not_nest_auth_pool_leases(self):
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import contextmanager
        from threading import Lock
        pool = Lock()

        @contextmanager
        def lease(*args):
            if not pool.acquire(timeout=1):
                raise AssertionError('Nested or exhausted auth pool')
            try:
                yield object()
            finally:
                pool.release()

        def safety(camera, connection, *, home):
            self.assertTrue(pool.locked())
            self.assertEqual(home, 'home')
            return False

        def claim(index):
            return updates.progress(str(index), updates.Progress(status='installing'),
                                    camera={'id': str(index), 'home_id': 'home'})['status']

        def jobs(_, camera):
            return [dict(id=camera, status='ready', scheduled_at=0)]

        with patch.object(updates, 'PG', True), patch.object(updates, 'transaction', lease), patch.object(updates, 'blocked', safety), patch.object(updates, 'jobs', jobs), patch.object(updates, 'state', return_value={'last_seen': time.time(), 'ready': True}), patch.object(updates, 'save'):
            with ThreadPoolExecutor(max_workers=4) as executor:
                self.assertEqual(list(executor.map(claim, range(8))), ['installing'] * 8)

    def test_claimed_restart_rolls_back_even_when_backend_is_offline(self):
        from fall_detect.update.updater import TemporaryNetworkError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'shared').mkdir()
            (root / 'shared/updater.json').write_text(json.dumps(
                {'backend_url': 'http://localhost', 'device_token': 'test'}))
            updater = Updater(root)
            self.addCleanup(updater.lock.close)
            atomic_json(updater.journal, {'job': {'id': 'job'}, 'old': '0.0.0', 'claimed': True})
            with patch.object(updater, 'report', side_effect=TemporaryNetworkError), patch.object(updater, 'switch') as switch, patch.object(updater, 'service'), patch.object(updater, 'healthy', return_value=True):
                with self.assertRaises(TemporaryNetworkError):
                    updater.recover()
                switch.assert_called_once_with('0.0.0')
                self.assertEqual(json.loads(updater.journal.read_text())['outcome'], 'rolled_back')
                with patch.object(updater, 'report'):
                    updater.recover()
                switch.assert_called_once()
                self.assertFalse(updater.journal.exists())

    def test_updater_declines_redirect_without_forwarding_token(self):
        from urllib.error import HTTPError
        from urllib.request import Request
        updater = object.__new__(Updater)
        updater.base, updater.token = 'https://example.com', 'test-token'
        redirect = HTTPError(updater.base, 302, '', {}, None)

        def build(handler):
            request = Request(updater.base, headers={'Authorization': 'Bearer test-token'})
            self.assertIsNone(handler.redirect_request(
                request, None, 302, '', {}, 'https://other.example'))
            class Opener:
                def open(self, request, timeout):
                    raise redirect
            return Opener()

        with patch('fall_detect.update.updater.urllib.request.build_opener', side_effect=build) as opener:
            with self.assertRaises(HTTPError):
                updater.request('job')
            opener.assert_called_once()

    def test_install_health_and_reporting_are_independent(self):
        from fall_detect.update.updater import TemporaryNetworkError
        for locally_healthy in (True, False):
            with self.subTest(locally_healthy=locally_healthy), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root/'shared').mkdir()
                (root/'shared/updater.json').write_text(json.dumps(
                    {'backend_url':'http://localhost','device_token':'test'}))
                with (root/'shared/updater.lock').open('a'):
                    updater = Updater(root)
                def report(job,status,*args):
                    if status != 'installing':
                        raise TemporaryNetworkError('offline')
                try:
                    with patch.object(updater,'current',return_value='0.0.0'), patch.object(updater,'local',return_value={'ready':True,'maintenance_active':True}), patch.object(updater,'report',side_effect=report), patch.object(updater,'healthy',side_effect=[locally_healthy,True]) as healthy, patch.object(updater,'switch') as switch, patch.object(updater,'service'):
                        with self.assertRaises(TemporaryNetworkError):
                            updater.install({'id':'test','version':'1.0.0'})
                        saved = json.loads(updater.journal.read_text())
                        self.assertEqual(saved['outcome'],'succeeded' if locally_healthy else 'rolled_back')
                        self.assertEqual(healthy.call_args_list[0].kwargs,{'require_backend':False})
                        self.assertEqual([c.args[0] for c in switch.call_args_list],
                                         ['1.0.0'] if locally_healthy else ['1.0.0','0.0.0'])
                finally:
                    updater.lock.close()

    def test_interrupted_download_leaves_job_retriable(self):
        from fall_detect.update.updater import TemporaryNetworkError
        updater = object.__new__(Updater)
        job = {'id':'test','status':'downloading'}
        with patch.object(updater,'recover'), patch.object(updater,'heartbeat',return_value={}), patch.object(updater,'request',return_value={'job':job}), patch.object(updater,'prepare',side_effect=TemporaryNetworkError), patch.object(updater,'report') as report:
            updater.tick()
            report.assert_called_once_with(job,'downloading')

    def test_restart_after_symlink_switch_preserves_releases_and_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared = root/'shared'
            shared.mkdir()
            (shared/'updater.json').write_text(json.dumps(
                {'backend_url':'http://localhost','device_token':'test'}))
            (shared/'app.env').write_text('fixture')
            updater = Updater(root)
            self.addCleanup(updater.lock.close)
            for version in ('0.0.0','1.0.0'):
                target = updater.target(version)
                target.mkdir()
                (target/'release.json').write_text('{}')
            updater.switch('1.0.0')
            atomic_json(updater.journal,{'job':{'id':'test'},'old':'0.0.0','claimed':True})
            with patch.object(updater,'service'), patch.object(updater,'healthy',return_value=True), patch.object(updater,'report'):
                updater.recover()
            self.assertEqual(updater.current(),'0.0.0')
            self.assertTrue(updater.target('1.0.0').exists())
            self.assertEqual((shared/'app.env').read_text(),'fixture')


class JournalPhaseTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        (root/'shared').mkdir()
        (root/'shared/updater.json').write_text(json.dumps(
            {'backend_url':'http://localhost','device_token':'fixture'}))
        self.updater = Updater(root)
        self.addCleanup(self.updater.lock.close)
        self.job = {'id':'job','version':'1.0.0'}

    def test_safety_revoked_after_claim_never_touches_service(self):
        updater = self.updater
        for ready, maintenance in ((False, False), (False, True), (True, False)):
            with self.subTest(ready=ready, maintenance=maintenance), patch.object(updater,'current',return_value='0.0.0'), patch.object(updater,'report') as report, patch.object(updater,'local',return_value={'ready':ready,'maintenance_active':maintenance}), patch.object(updater,'service') as service, patch.object(updater,'switch') as switch:
                with self.assertRaises(RuntimeError):
                    updater.install(self.job)
                service.assert_not_called()
                switch.assert_not_called()
                self.assertEqual([call.args[1] for call in report.call_args_list], ['installing','failed'])

    def test_restart_phase_controls_rollback(self):
        updater = self.updater
        for phase in ('claim_pending','claimed','modifying','switched','restored'):
            with self.subTest(phase=phase):
                atomic_json(updater.journal,{'phase':phase,'job':self.job,'old':'0.0.0',
                                            'claimed':phase != 'claim_pending'})
                with patch.object(updater,'request',return_value={'job':{**self.job,'status':'installing'}}), patch.object(updater,'report',side_effect=OSError('offline')), patch.object(updater,'service') as service, patch.object(updater,'switch') as switch, patch.object(updater,'healthy',return_value=True):
                    with self.assertRaises(OSError):
                        updater.recover()
                    outcome = json.loads(updater.journal.read_text())
                    self.assertEqual(outcome['phase'],'report_pending')
                    if phase in ('modifying','switched'):
                        self.assertEqual([call.args[0] for call in service.call_args_list],['stop','start'])
                        switch.assert_called_once_with('0.0.0')
                    else:
                        service.assert_not_called()
                        switch.assert_not_called()
                    self.assertEqual(outcome['outcome'],'failed' if phase in ('claim_pending','claimed') else 'rolled_back')
                    with patch.object(updater,'report'):
                        updater.recover()
                    self.assertFalse(updater.journal.exists())
                    self.assertEqual(switch.call_count,int(phase in ('modifying','switched')))
