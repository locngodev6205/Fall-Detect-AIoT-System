"""Focused fast-track cases. Real provider sends are never performed here."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json,re,secrets,time
from unittest.mock import patch
import smtplib


def reset_otp_case(case,postgres=False):
    if postgres:
        from backend.src import pgdb as db,pgservices as svc,pgsecurity as sec
    else:
        from backend.src import db,services as svc,security as sec
    client,account=case.account('fasttrack-reset@example.test');email=account['email']
    def latest():
        with db.connect('auth') if postgres else db.connect() as conn:
            if postgres:
                row=conn.execute("SELECT secret_ciphertext FROM annha_private.job_queue WHERE kind='email' AND payload->>'purpose'='reset_password' ORDER BY created_at DESC LIMIT 1").fetchone();data=svc.decrypt(row['secret_ciphertext'])
            else:
                row=conn.execute("SELECT body,html_body,secret_ciphertext FROM mail_jobs WHERE recipient=? AND secret_ciphertext IS NOT NULL ORDER BY created_at DESC,rowid DESC LIMIT 1",(email,)).fetchone()
                case.assertEqual(row['body'],'');case.assertIsNone(row['html_body']);data=json.loads(svc.mail_cipher().decrypt(row['secret_ciphertext']))
        code=re.search(r'Mã đặt lại mật khẩu: (\d{8})',data['body'])[1]
        case.assertIn(code,data['html_body']);case.assertIn('15 phút',data['body']);case.assertNotIn('href=',data['html_body'])
        return code
    known=client.post('/api/auth/forgot',json={'email':email});unknown=client.post('/api/auth/forgot',json={'email':'missing-fasttrack@example.test'})
    case.assertEqual((known.status_code,known.json()),(unknown.status_code,unknown.json()))
    first=latest();hashed=sec.reset_code_digest(email,first)
    case.assertNotEqual(hashed,sec.verification_code_digest(first))
    with db.connect('auth') if postgres else db.connect() as conn:
        row=conn.execute('SELECT * FROM annha_private.email_tokens WHERE token_hash=%s' if postgres else 'SELECT * FROM email_tokens WHERE token_hash=?',(hashed,)).fetchone()
    case.assertIsNotNone(row)
    seconds=(row['expires_at']-row['created_at']).total_seconds() if postgres else row['expires']-time.time()
    case.assertTrue(895<seconds<=901)
    def check(code,who=email):return client.post('/api/auth/reset/check',json={'email':who,'code':code})
    case.assertEqual(check(first,'different@example.test').status_code,400)
    wrong=f'{(int(first)+1)%100_000_000:08d}'
    case.assertEqual(check(wrong).status_code,400)
    case.assertEqual(check(first).status_code,200)
    client.post('/api/auth/forgot',json={'email':email});second=latest();case.assertNotEqual(first,second)
    case.assertEqual(check(first).status_code,400)
    with db.connect('auth') if postgres else db.connect() as conn:
        if postgres:conn.execute("UPDATE annha_private.email_tokens SET created_at=now()-interval '16 minutes',expires_at=now()-interval '1 minute' WHERE token_hash=%s",(sec.reset_code_digest(email,second),))
        else:conn.execute('UPDATE email_tokens SET expires=? WHERE token_hash=?',(time.time()-1,sec.reset_code_digest(email,second)))
    case.assertEqual(check(second).status_code,400)
    case.assertEqual(client.post('/api/auth/forgot',json={'email':email}).status_code,200);third=latest()
    case.assertEqual(client.post('/api/auth/forgot',json={'email':email}).status_code,429)
    passwords=['new fasttrack password 123','new fasttrack password 456']
    def reset(item):
        index,who=item
        return who.post('/api/auth/reset',json={'email':email,'code':third,'password':passwords[index]}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(reset,enumerate((client,case.client))))
    case.assertEqual(sorted(statuses),[200,400]);winner=passwords[statuses.index(200)]
    case.assertEqual(client.get('/api/auth/me').status_code,401)
    case.assertEqual(client.post('/api/auth/login',json={'email':email,'password':'correct password 123'}).status_code,401)
    case.assertEqual(client.post('/api/auth/login',json={'email':email,'password':winner}).status_code,200)
    case.assertEqual(client.post('/api/auth/reset',json={'email':email,'code':third,'password':passwords[0]}).status_code,400)
    # Seven attempts against this email above; the next three fill the window.
    for _ in range(3):case.assertEqual(check(wrong).status_code,400)
    case.assertEqual(check(wrong).status_code,429)
    legacy=secrets.token_urlsafe(32)
    with db.connect('auth') if postgres else db.connect() as conn:
        if postgres:
            version=conn.execute('SELECT email_version FROM annha_private.users WHERE id=%s',(account['id'],)).fetchone()['email_version']
            conn.execute("INSERT INTO annha_private.email_tokens(token_hash,user_id,purpose,expires_at,email_version) VALUES(%s,%s,'reset_password',%s,%s)",(sec.digest(legacy),account['id'],db.now()+timedelta(minutes=15),version))
        else:conn.execute('INSERT INTO email_tokens VALUES(?,?,?,?)',(sec.digest(legacy),account['id'],'reset',time.time()+900))
    case.assertEqual(case.client.post('/api/auth/reset',json={'token':legacy,'password':passwords[0]}).status_code,200)


def safety_retry_case(case):
    from backend.src import pgdb as db,pgservices as svc
    owner,user=case.account('fasttrack-alert@example.test');home,room,camera,provision=case.home_camera(owner)
    device=case.device(provision)
    policy={'telegram':{'enabled':False},'email':{'enabled':True,'event_kinds':['fall'],'minimum_severity':'warning','camera_scope_all':True,'camera_ids':[]}}
    with patch.dict('os.environ',{'EMAIL_ALERTS_ENABLED':'true'}):
        saved=owner.put(f"/api/homes/{home['id']}/notification-recipients/{user['id']}",json=policy);case.assertEqual(saved.status_code,200)
        response=device.post('/api/device/events',json={'event_id':'fasttrack-smtp-retry','kind':'fall','severity':'critical','observation':'abnormal','observed_at':db.now().isoformat(),'reason':'Cảnh báo tổng hợp kiểm thử'})
        case.assertEqual(response.status_code,200)
        with db.connect('worker',home['id']) as conn:
            job=conn.execute("SELECT d.id FROM annha.notification_deliveries d JOIN annha.notification_channels c ON c.id=d.channel_id WHERE d.home_id=%s AND c.kind='email'",(home['id'],)).fetchone()
        with patch.object(svc,'send_mail',side_effect=smtplib.SMTPResponseException(451,b'synthetic temporary failure')) as send:
            svc.process_notifications(home['id'],str(job['id']));send.assert_called_once()
        with db.connect('worker',home['id']) as conn:
            failed=conn.execute('SELECT status,attempt_count,sent_count,next_attempt_at>now() AS delayed FROM annha.notification_deliveries WHERE id=%s',(job['id'],)).fetchone()
            case.assertEqual((failed['status'],failed['attempt_count'],failed['sent_count'],failed['delayed']),('pending',1,0,True))
            conn.execute('UPDATE annha.notification_deliveries SET next_attempt_at=now() WHERE id=%s',(job['id'],))
        with patch.object(svc,'send_mail') as send:
            svc.process_notifications(home['id'],str(job['id']));svc.process_notifications(home['id'],str(job['id']));send.assert_called_once()
            args=send.call_args.args;case.assertEqual(args[0],user['email']);case.assertEqual(args[1],'AnNhà · Thông tin an toàn cần lưu ý');case.assertIn(home['name'],args[2]);case.assertIn('viewport',args[3])
        with db.connect('worker',home['id']) as conn:
            result=conn.execute('SELECT status,attempt_count,sent_count FROM annha.notification_deliveries WHERE id=%s',(job['id'],)).fetchone()
            attempts=conn.execute('SELECT status FROM annha.delivery_attempts WHERE delivery_id=%s ORDER BY attempt',(job['id'],)).fetchall()
        case.assertEqual((result['status'],result['attempt_count'],result['sent_count']),('accepted',2,1));case.assertEqual([r['status'] for r in attempts],['failed','accepted'])
