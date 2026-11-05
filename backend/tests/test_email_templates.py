import os
import ssl
import unittest
from unittest.mock import patch
from contextlib import contextmanager
from types import SimpleNamespace
from pydantic import ValidationError

from backend.src.email_templates import render_email
from backend.src import pgapi, pgservices, models


class EmailTemplateTests(unittest.TestCase):
    def test_all_approved_templates_have_html_text_cta_and_safe_fallback_link(self):
        samples = {
            'verification': {'recipient_name': 'Nguyễn An', 'code': '01234567'},
            'password_reset': {'recipient_name': 'Nguyễn An', 'code': '01234567'},
            'invitation': {'recipient_name': 'Nguyễn An', 'inviter_name': 'Chủ nhà', 'home_name': 'Nhà AnNhà',
                           'role_label': 'Người chăm sóc', 'scope_text': 'Phòng khách', 'token': 'invite-789'},
            'safety_alert': {'recipient_name': 'Nguyễn An', 'home_name': 'Nhà AnNhà', 'room_name': 'Phòng khách',
                             'camera_name': 'Camera cửa chính', 'severity_label': 'Cần lưu ý',
                             'event_label': 'Nghi ngờ té ngã', 'occurred_at': '08:30 05/11/2026',
                             'event_id': 'event-abc'},
        }
        for kind, values in samples.items():
            with self.subTest(template=kind):
                result = render_email(kind, public_url='https://annha.example', **values)
                self.assertTrue(result.subject)
                self.assertTrue(result.preheader)
                self.assertIn('viewport', result.html)
                self.assertIn('Nhà an tâm, mình an lòng', result.html)
                self.assertIn('Nhà an tâm, mình an lòng', result.text)
                if kind in ('verification','password_reset'):
                    self.assertIn('01234567', result.html)
                    self.assertIn('01234567', result.text)
                    self.assertNotIn('href=', result.html)
                    self.assertNotIn('https://annha.example/', result.text)
                else:
                    self.assertIn('href="https://annha.example/', result.html)
                    self.assertIn('https://annha.example/', result.text)
                    self.assertIn('sao chép liên kết', result.html)
                expected_cta = {'verification': 'Mã xác minh', 'password_reset': 'Mã đặt lại mật khẩu',
                                'invitation': 'Xem lời mời', 'safety_alert': 'Mở sự kiện'}[kind]
                self.assertIn(expected_cta, result.text)

    def test_user_content_is_escaped_and_long_values_wrap(self):
        hostile = '<img src=x onerror="alert(1)"> & Nhà'
        result = render_email('invitation', public_url='https://annha.example', recipient_name=hostile,
                              inviter_name=hostile, home_name=hostile * 40, role_label='Người xem',
                              scope_text=hostile * 60, token='safe-token')
        self.assertNotIn('<img src=x', result.html)
        self.assertIn('&lt;img src=x', result.html)
        self.assertIn('overflow-wrap:anywhere', result.html)
        self.assertIn(hostile, result.text)

    def test_verification_email_has_prominent_code_and_no_deployment_link(self):
        result = render_email('verification', public_url='http://localhost:8188',
                              recipient_name='Người nhận thử', code='00123456')
        self.assertEqual(result.subject, 'Mã xác minh email AnNhà')
        self.assertIn('font-size:32px', result.html)
        self.assertIn('00123456', result.html)
        self.assertIn('00123456', result.text)
        self.assertNotIn('localhost', result.html + result.text)
        self.assertIn('24 giờ', result.text)

    def test_verification_code_requires_exactly_eight_digits(self):
        with self.assertRaises(ValueError):
            render_email('verification')
        for code in ('1234567', '123456789', '12ab5678'):
            with self.subTest(code=code), self.assertRaises(ValueError):
                render_email('verification', code=code)

    def test_rejects_unsafe_public_urls(self):
        for url in ('javascript:alert(1)', 'data:text/html,hello', 'https://user:secret@example.test',
                    'https://annha.example/?redirect=bad', 'https://annha.example/#/wrong'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                render_email('invitation', public_url=url, token='x')

    def test_smtp_message_can_include_plain_text_and_html_alternatives(self):
        sent = []

        class FakeSMTP:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def send_message(self, message): sent.append(message)

        with patch.dict(os.environ, {'SMTP_HOST': 'mail.invalid', 'SMTP_PORT': '1025'}), \
             patch('backend.src.pgservices.smtplib.SMTP', FakeSMTP):
            pgservices.send_mail('recipient@example.test', 'Subject', 'Plain body', '<p>HTML body</p>')
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0].is_multipart())
        parts = list(sent[0].iter_parts())
        self.assertEqual(parts[0].get_content_type(), 'text/plain')
        self.assertEqual(parts[0].get_content().strip(), 'Plain body')
        self.assertEqual(parts[1].get_content_type(), 'text/html')
        self.assertIn('HTML body', parts[1].get_content())

    def test_brevo_requires_verified_starttls_and_authenticated_smtp(self):
        calls = []

        class FakeSMTP:
            def __init__(self, host, port, timeout): calls.append(('connect', host, port, timeout))
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def ehlo(self): calls.append(('ehlo',))
            def starttls(self, context): calls.append(('starttls', context.check_hostname, context.verify_mode))
            def login(self, username, password): calls.append(('login', username, password))
            def send_message(self, message): calls.append(('send', message['To']))

        env = {'SMTP_HOST':'smtp-relay.brevo.com','SMTP_PORT':'587','SMTP_STARTTLS':'true',
               'SMTP_USER':'login@example.test','SMTP_PASSWORD':'synthetic-smtp-key',
               'SMTP_FROM':'AnNhà <noreply@example.test>'}
        with patch.dict(os.environ, env), patch('backend.src.pgservices.smtplib.SMTP', FakeSMTP):
            pgservices.send_mail('recipient@example.test','Subject','Plain body')
        self.assertIn(('starttls', True, ssl.CERT_REQUIRED), calls)
        self.assertIn(('login','login@example.test','synthetic-smtp-key'), calls)
        self.assertIn(('send','recipient@example.test'), calls)

        unsafe = {**env,'SMTP_STARTTLS':'false'}
        with patch.dict(os.environ, unsafe), patch('backend.src.pgservices.smtplib.SMTP') as connect:
            with self.assertRaisesRegex(RuntimeError,'BrevoSMTPRequiresAuthenticatedStartTLS'):
                pgservices.send_mail('recipient@example.test','Subject','Plain body')
            connect.assert_not_called()

    def test_account_email_is_rendered_and_queued_with_encrypted_html_payload(self):
        account = {'id': 'account-1', 'email': 'person@example.test', 'name': 'Nguyễn An', 'email_version': 3}
        statements = []

        class Conn:
            def execute(self, sql, params): statements.append((sql, params))

        queued = []
        with patch.object(pgservices.secrets, 'randbelow', return_value=1234567), \
             patch.object(pgservices.db, 'now', return_value=__import__('datetime').datetime(2026, 11, 5, tzinfo=__import__('datetime').timezone.utc)), \
             patch.object(pgservices, 'mail', side_effect=lambda *args: queued.append(args)), \
             patch.dict(os.environ, {'PUBLIC_URL': 'https://annha.example','SESSION_CSRF_KEY':'reset-unit-key-only-not-for-deployment'}):
            pgservices.queue_email(Conn(), account, 'reset_password')

        self.assertEqual(len(statements), 3)
        self.assertEqual(len(queued), 1)
        _, recipient, subject, text, purpose, html = queued[0]
        self.assertEqual((recipient, purpose), ('person@example.test', 'reset_password'))
        self.assertNotIn('https://annha.example', text)
        self.assertIn('01234567', html)
        self.assertIn('15 phút', text)
        self.assertEqual(subject, 'Mã đặt lại mật khẩu AnNhà')

    def test_verification_email_queues_only_a_hmac_of_the_code_and_html(self):
        account = {'id': 'account-2', 'email': 'verify@example.test', 'name': 'Người nhận thử', 'email_version': 1}
        statements=[];queued=[]

        class Conn:
            def execute(self, sql, params): statements.append((sql,params))

        with patch.object(pgservices.secrets,'randbelow',return_value=123456), \
             patch.object(pgservices.db,'now',return_value=__import__('datetime').datetime(2026,11,5,tzinfo=__import__('datetime').timezone.utc)), \
             patch.object(pgservices,'mail',side_effect=lambda *args: queued.append(args)), \
             patch.dict(os.environ,{'PUBLIC_URL':'http://localhost:8188','SESSION_CSRF_KEY':'test-csrf-secret-long-enough-for-tests'}):
            pgservices.queue_email(Conn(),account,'verify_email')

        self.assertEqual(len(queued),1)
        _,recipient,subject,body,purpose,html=queued[0]
        self.assertEqual((recipient,purpose,subject),('verify@example.test','verify_email','Mã xác minh email AnNhà'))
        self.assertIn('Mã xác minh: 00123456',body)
        self.assertIn('00123456',html)
        self.assertNotIn('localhost',html+body)
        self.assertNotIn('00123456',str(statements[-1][1][0]))

    def test_verify_email_request_accepts_one_code_or_legacy_link_token(self):
        self.assertEqual(models.VerifyEmail(code='12345678').code,'12345678')
        self.assertEqual(models.VerifyEmail(token='a'*32).token,'a'*32)
        for payload in ({}, {'code':'12345678','token':'a'*32}, {'code':'1234abcd'}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                models.VerifyEmail.model_validate(payload)

    def test_safety_alert_template_uses_private_event_context_and_event_route(self):
        from datetime import datetime, timezone
        event = {'id': 'event-123', 'kind': 'fall', 'severity': 'critical',
                 'first_observed_at': datetime(2026, 11, 5, 1, 30, tzinfo=timezone.utc),
                 'timezone': 'Asia/Ho_Chi_Minh', 'home_name': 'Nhà AnNhà',
                 'room_name': 'Phòng khách', 'camera_name': 'Camera cửa chính'}
        with patch.dict(os.environ, {'PUBLIC_URL': 'https://annha.example'}):
            rendered = pgservices.format_safety_email(event, 'Nguyễn An')
        self.assertIn('https://annha.example/#/event/event-123', rendered.text)
        self.assertIn('Nghiêm trọng', rendered.text)
        self.assertIn('05/11/2026 08:30:00', rendered.text)
        self.assertIn('không đính kèm ảnh hoặc video', rendered.text)

    def test_email_job_worker_passes_html_alternative_to_smtp(self):
        from contextlib import contextmanager

        job = {'id': 'job-1', 'kind': 'email', 'secret_ciphertext': b'ciphertext', 'attempts': 1,
               'home_id': None, 'asset_id': None}
        calls = []

        class Result:
            def __init__(self, row=None): self.row = row
            def fetchone(self): return self.row

        class Conn:
            def __init__(self, pick): self.pick = pick
            def execute(self, *args):
                calls.append(args)
                return Result(job if self.pick else None)

        opened = 0
        def connect(*args, **kwargs):
            nonlocal opened
            opened += 1
            @contextmanager
            def context(): yield Conn(opened == 1)
            return context()

        payload = {'recipient': 'person@example.test', 'subject': 'Subject',
                   'body': 'Plain body', 'html_body': '<p>HTML body</p>'}
        with patch.object(pgservices.db, 'uid', return_value='lease-1'), \
             patch.object(pgservices.db, 'connect', side_effect=connect), \
             patch.object(pgservices, 'decrypt', return_value=payload), \
             patch.object(pgservices, 'send_mail') as send_mail:
            pgservices.process_job(job_id='job-1', kinds=['email'])
        send_mail.assert_called_once_with('person@example.test', 'Subject', 'Plain body', '<p>HTML body</p>')


class EmailRequestPrivacyTests(unittest.TestCase):
    def test_forgot_and_resend_return_same_message_for_known_and_unknown_addresses(self):
        request = SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'))
        account = {'id': 'account-1', 'email': 'known@example.test'}

        class Result:
            def __init__(self, row): self.row = row
            def fetchone(self): return self.row

        class Conn:
            def __init__(self, row): self.row = row
            def execute(self, *args, **kwargs): return Result(self.row)

        for endpoint in (pgapi.forgot, pgapi.resend):
            with self.subTest(endpoint=endpoint.__name__):
                def connect(*args, **kwargs):
                    @contextmanager
                    def opened(): yield Conn(state['account'])
                    return opened()

                state = {'account': None}
                with patch.object(pgapi, 'throttle'), patch.object(pgapi.db, 'connect', side_effect=connect), \
                     patch.object(pgapi.svc, 'queue_email') as queue:
                    unknown = endpoint(models.Email(email='unknown@example.test'), request)
                    state['account'] = account
                    known = endpoint(models.Email(email='known@example.test'), request)
                self.assertEqual(unknown, known)
                self.assertIn('hệ thống sẽ gửi', unknown['message'])
                self.assertEqual(queue.call_count, 1)


if __name__ == '__main__':
    unittest.main()


class ResetOTPContractTests(unittest.TestCase):
    def test_reset_html_code_no_domain_and_missing_code_rejected(self):
        rendered=render_email('password_reset',public_url='not-needed',code='00123456',recipient_name='Người nhận thử')
        self.assertEqual(rendered.subject,'Mã đặt lại mật khẩu AnNhà')
        self.assertIn('00123456',rendered.html);self.assertIn('font-size:32px',rendered.html)
        self.assertIn('15 phút',rendered.text);self.assertNotIn('href=',rendered.html)
        with self.assertRaises(ValueError):render_email('password_reset')

    def test_reset_code_requires_email_and_preserves_legacy_token(self):
        value=models.Reset(email=' OWNER@EXAMPLE.TEST ',code='00123456',password='  new password 123  ')
        self.assertEqual(value.email,'owner@example.test');self.assertEqual(value.password,'  new password 123  ')
        self.assertEqual(models.Reset(token='x'*32,password='new password 123').token,'x'*32)
        for data in ({'code':'00123456'},{'email':'owner@example.test','code':'123abcde'},{'email':'owner@example.test','code':'00123456','token':'x'*32}):
            with self.subTest(keys=sorted(data)),self.assertRaises(ValidationError):models.Reset(**data,password='new password 123')
