"""Integration tests for the disposable loopback OTA database only."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from threading import Barrier
import time
import unittest
from uuid import uuid4

from fastapi import HTTPException


@unittest.skipUnless(os.getenv('ANNHA_OTA_LOCAL_PG') == '1', 'Requires disposable PostgreSQL container')
class LocalOTA(unittest.TestCase):
    def test_pool_one(self):
        self.exercise(1)

    def test_pool_two(self):
        self.exercise(2)

    def exercise(self, size):
        from cryptography.fernet import Fernet
        import psycopg
        from backend.src import device_updates as ota
        from unittest.mock import patch
        self.assertTrue(ota.PG)
        env = {f'DATABASE_URL_{role.upper()}': f'postgresql://ota_{role}@127.0.0.1:55482/postgres'
               for role in ota.db.ROLES}
        env.update(ANNHA_TEST_ENV='local-ota', ANNHA_TEST_SSL_MODE='disable',
                   DATABASE_POOL_MAX=str(size), SESSION_CSRF_KEY='test-only-' * 4,
                   DATA_ENCRYPTION_KEY=Fernet.generate_key().decode())
        owner, home, room, first, second, d1, d2 = map(str, (uuid4() for _ in range(7)))
        cameras = [dict(id=first, home_id=home), dict(id=second, home_id=home)]
        with psycopg.connect('postgresql://postgres@127.0.0.1:55482/postgres') as admin:
            admin.execute('INSERT INTO annha_private.users(id,email,name,password_hash) VALUES(%s,%s,%s,%s)',
                          (owner, owner+'@example.test', 'Owner', 'fixture'))
            admin.execute('INSERT INTO annha.homes(id,name,created_by) VALUES(%s,%s,%s)', (home,'Home',owner))
            admin.execute("INSERT INTO annha_private.home_memberships(home_id,user_id,role) VALUES(%s,%s,'owner')",(home,owner))
            admin.execute('INSERT INTO annha.rooms(id,home_id,name) VALUES(%s,%s,%s)', (room,home,'Room'))
            for camera, device in zip(cameras, (d1,d2)):
                admin.execute('INSERT INTO annha_private.device_registry(id) VALUES(%s)',(device,))
                admin.execute('INSERT INTO annha.cameras(id,home_id,room_id,device_id,name) VALUES(%s,%s,%s,%s,%s)',
                              (camera['id'],home,room,device,'Camera'))
        with patch.dict(os.environ,env):
            ota.db.open_pools()
            try:
                def seed(camera):
                    cid = camera['id']
                    now = time.time()
                    job = dict(id=str(uuid4()),camera_id=cid,status='ready',created_at=now,
                               scheduled_at=now-1,expires_at=now+60)
                    ota.heartbeat(ota.AgentState(ready=True),camera)
                    with ota.transaction(cid) as c:
                        c.execute('INSERT INTO update_jobs(id,camera_id,payload) VALUES(?,?,?)',
                                  (job['id'],cid,json.dumps(job)))
                    return job['id']
                def claim(camera, job):
                    return ota.progress(job,ota.Progress(status='installing'),camera)['status']
                def race(callables):
                    barrier = Barrier(len(callables))
                    def run(call):
                        barrier.wait()
                        try:
                            return call()
                        except HTTPException as exc:
                            return exc.status_code
                    with ThreadPoolExecutor(max_workers=len(callables)) as pool:
                        return list(pool.map(run,callables))
                jobs = [seed(camera) for camera in cameras]
                with self.assertRaises(HTTPException) as rejected:
                    claim(cameras[1], jobs[0])
                self.assertEqual(rejected.exception.status_code,404)
                self.assertEqual(race([lambda i=i: claim(cameras[i%2],jobs[i%2]) for i in range(8)]),
                                 ['installing']*8)
                for _ in range(6):
                    job = seed(cameras[0])
                    result = race([lambda: claim(cameras[0],job),
                                   lambda: ota.cancel(first,job,{'id':owner})['status']])
                    self.assertIn(result, (['installing',409],[409,'cancelled']))
                with psycopg.connect('postgresql://postgres@127.0.0.1:55482/postgres') as admin:
                    admin.execute("""INSERT INTO annha.events(home_id,camera_id,source_id,kind,severity,
                                  observation,first_observed_at,last_observed_at)
                                  VALUES(%s,%s,'test','fall','critical','suspected',now(),now())""",(home,first))
                self.assertTrue(ota.blocked(first,home=home))
                self.assertFalse(ota.blocked(second,home=home))
                job = seed(cameras[0])
                self.assertEqual(race([lambda: claim(cameras[0],job)]),[409])
            finally:
                ota.db.close_pools()
