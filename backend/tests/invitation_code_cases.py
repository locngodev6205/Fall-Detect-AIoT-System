"""Focused shared invitation-code scenarios; no SMTP or hardware calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import time
from backend.src import invitation_codes as codes


def exercise(case,postgres=False):
    if postgres:
        from backend.src import pgdb as db
    else:
        from backend.src import db
    owner,_=case.account('code-owner@example.test')
    member,member_user=case.account('code-member@example.test')
    other,other_user=case.account('code-other@example.test')
    home,_,camera,_=case.home_camera(owner);home_id=home['id']
    path=f'/api/homes/{home_id}/invitation-codes'
    def create():
        response=owner.post(path,json={});case.assertEqual(response.status_code,201,response.text)
        return response.json()
    def join(client,item):return client.post('/api/invitation-codes/join',json={'code':item['code']})
    def email_count():
        with db.connect('auth') if postgres else db.connect() as conn:
            return conn.execute("SELECT count(*) AS n FROM annha_private.job_queue WHERE kind='email'" if postgres else 'SELECT count(*) AS n FROM mail_jobs').fetchone()['n']
    before=email_count();first=create()
    case.assertEqual(len(codes.normalize(first['code'])),16)
    case.assertEqual(first['role'],'member')
    with db.connect('auth') if postgres else db.connect() as conn:
        stored=conn.execute('SELECT code_hash FROM annha_private.invitation_codes WHERE id=%s' if postgres else 'SELECT code_hash FROM invitation_codes WHERE id=?',(first['id'],)).fetchone()
    case.assertEqual(bytes(stored['code_hash']),codes.code_hash(first['code']))
    case.assertEqual(member.get(path).status_code,404)
    case.assertEqual(member.post(path,json={}).status_code,404)
    case.assertEqual(case.client.post('/api/invitation-codes/join',json={'code':first['code']}).status_code,401)
    case.assertEqual(join(member,first).status_code,200)
    case.assertEqual(next(h for h in member.get('/api/homes').json() if h['id']==home_id)['role'],'member')
    visible=member.get(f'/api/homes/{home_id}/cameras');case.assertEqual(visible.status_code,200)
    case.assertEqual([c['id'] for c in visible.json()],[camera['id']])
    rights=visible.json()[0]['permissions'];case.assertTrue(rights['view']);case.assertFalse(rights['audio']);case.assertFalse(rights['schedules']);case.assertFalse(rights['events'])
    case.assertEqual(member.post(path,json={}).status_code,403)
    case.assertEqual(join(member,first).status_code,400)
    case.assertEqual(join(other,first).status_code,400)
    duplicate=create();case.assertEqual(join(member,duplicate).status_code,409)
    # Already a member must not consume someone else's still-active invitation.
    case.assertEqual(next(x for x in owner.get(path).json() if x['id']==duplicate['id'])['status'],'active')
    expired=create()
    with db.connect('auth') if postgres else db.connect() as conn:
        if postgres:
            conn.execute("UPDATE annha_private.invitation_codes SET created_at=now()-interval '8 days',expires_at=now()-interval '1 day' WHERE id=%s",(expired['id'],))
        else:conn.execute('UPDATE invitation_codes SET expires_at=? WHERE id=?',(time.time()-1,expired['id']))
    case.assertEqual(join(other,expired).status_code,400)
    revoked=create();case.assertEqual(owner.delete(path+'/'+revoked['id']).status_code,200)
    case.assertEqual(join(other,revoked).status_code,400)
    with db.connect('auth') if postgres else db.connect() as conn:
        conn.execute('UPDATE annha_private.users SET email_verified_at=NULL WHERE id=%s' if postgres else 'UPDATE users SET verified=0 WHERE id=?',(other_user['id'],))
    case.assertEqual(join(other,duplicate).status_code,403)
    with db.connect('auth') if postgres else db.connect() as conn:
        conn.execute('UPDATE annha_private.users SET email_verified_at=now() WHERE id=%s' if postgres else 'UPDATE users SET verified=1 WHERE id=?',(other_user['id'],))
    case.assertEqual(other.post('/api/invitation-codes/join',json={'code':'AAAA-AAAA-AAAA-AAAA'}).status_code,400)
    # Different accounts redeem the same code concurrently: exactly one succeeds.
    second=owner.post('/api/homes',json={'name':'Nhà kiểm tra đồng thời'}).json()
    race=owner.post(f"/api/homes/{second['id']}/invitation-codes",json={}).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda client:join(client,race).status_code,(member,other)))
    case.assertEqual(sorted(results),[200,400])
    case.assertEqual(other.post('/api/invitation-codes/join',json={'code':'BBBB-BBBB-BBBB-BBBB'}).status_code,429)
    listing=owner.get(path).json()
    case.assertEqual(next(x for x in listing if x['id']==first['id'])['status'],'used')
    case.assertTrue(all('code' not in item and 'code_hash' not in item for item in listing))
    case.assertEqual(email_count(),before,'Invitation codes must not enqueue invitation emails')
    if postgres:
        import psycopg
        with case.assertRaises(psycopg.errors.InsufficientPrivilege):
            with db.connect('app',home_id,member_user['id']) as conn:conn.execute('SELECT * FROM annha_private.invitation_codes')
