import os
import unittest

from backend.src import pgdb as db, pgservices as services


class EvidenceNotificationUnitTests(unittest.TestCase):
    """Offline regression tests: all database, SMTP and Telegram calls are mocked."""

    def test_smtp_optional_image_and_transactional_compatibility(self):
        from unittest.mock import patch
        from backend.src.email_templates import render_email
        with patch.object(services.smtplib,'SMTP') as smtp:
            services.send_mail('fixture@example.invalid','Fall','text','<p>text</p>',
                attachment=(b'\xff\xd8\xffimage','image/jpeg','fall_event.jpg'))
            message=smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertEqual([(p.get_filename(),p.get_content_type()) for p in message.iter_attachments()],
                             [('fall_event.jpg','image/jpeg')])
            for kind in ('verification','password_reset','invitation'):
                rendered=render_email(kind,code='12345678',token='fixture')
                services.send_mail('fixture@example.invalid',rendered.subject,rendered.text,rendered.html)
                message=smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
                self.assertEqual(list(message.iter_attachments()),[])
            for mime,data in [('text/plain',b'x'),('image/png',b'x'*(5*1024*1024+1))]:
                with self.assertRaises(ValueError):
                    services.send_mail('fixture@example.invalid','test','text',attachment=(data,mime,'test'))

    def run_delivery(self,channel_kind='telegram',kind='fall',consent=True,image=True,
                     age=60,reject=False,eligible=True,revoke=False,read_result=None,ambiguous=False,wait_seconds=3):
        from unittest.mock import MagicMock,patch
        now=db.now()
        job={'id':'delivery','channel_id':'channel','event_id':'event','camera_id':'camera',
             'created_at':now-services.timedelta(seconds=age),'attempt_count':0,'email_version':1}
        channel={'id':'channel','recipient_user_id':'user','kind':channel_kind,'allow_media':consent}
        event={'id':'event','kind':kind,'severity':'critical','first_observed_at':now,
               'home_name':'Home','timezone':'UTC','camera_name':'Camera','room_name':'Room','reason':'Fixture reason'}
        evidence={'mime_type':'image/png'} if image else None
        updates=[];queries=[];state=['pending']
        conn=MagicMock();conn.__enter__.return_value=conn
        def execute(sql,args=()):
            queries.append((sql,args));result=MagicMock()
            if sql.startswith('SELECT * FROM annha.notification_deliveries'): row=job if state[0]=='pending' else None
            elif 'can_dispatch_notification' in sql: row={'ok':eligible}
            elif sql.startswith('SELECT * FROM annha.notification_channels'): row=channel
            elif sql.startswith('SELECT e.*'): row=event
            elif sql.startswith('SELECT destination_ciphertext'): row={'destination_ciphertext':'fixture'}
            elif sql.startswith('SELECT * FROM annha.media_assets'): row=evidence
            elif sql.startswith('SELECT email,name'): row={'email':'fixture@example.invalid','name':'Fixture','email_version':1}
            elif sql.startswith('SELECT allow_media'): row={'allow_media':consent and not revoke}
            elif sql.startswith('SELECT c.allow_media'): row={'allow_media':consent and not revoke,'destination_ciphertext':'fixture'}
            else: row=None
            if sql.startswith('UPDATE annha.notification_deliveries SET status=%s'):
                state[0]=args[0];updates.append(args)
            if "status='cancelled'" in sql: state[0]='cancelled'
            result.fetchone.return_value=row
            return result
        conn.execute.side_effect=execute
        with patch.object(db,'connect',return_value=conn), \
             patch.dict(os.environ,{'EMAIL_ALERTS_ENABLED':'true','TELEGRAM_BOT_TOKEN':'offline-fixture','NOTIFICATION_EVIDENCE_WAIT_SECONDS':str(wait_seconds)}), \
             patch.object(services,'decrypt',return_value={'chat_id':'123'}), \
             patch.object(services,'_read_notification_image',return_value=read_result or (b'\x89PNG\r\n\x1a\nfixture','sent')), \
             patch.object(services,'send_mail') as mail, \
             patch.object(services,'send_telegram_photo',return_value='photo') as photo, \
             patch.object(services,'send_telegram_text',return_value='text') as text:
            if reject: photo.side_effect=services.TelegramDeliveryError('TelegramPhotoRejected')
            if ambiguous: photo.side_effect=services.TelegramDeliveryError('TelegramTimeout',ambiguous=True)
            services.process_notifications('home','delivery')
            services.process_notifications('home','delivery')
        return mail,photo,text,updates,queries,state[0]

    def test_allowed_images_each_event_kind_and_channel(self):
        for kind in ('fall','immobility','environment','device'):
            for channel in ('email','telegram'):
                with self.subTest(kind=kind,channel=channel):
                    mail,photo,text,updates,queries,state=self.run_delivery(channel,kind)
                    self.assertEqual(state,'accepted');self.assertEqual(len(updates),1)
                    if channel=='email':
                        self.assertEqual(mail.call_count,1)
                        self.assertEqual(mail.call_args.kwargs['attachment'][2],kind+'_event.png')
                    else:
                        self.assertEqual(photo.call_count,1);text.assert_not_called()
                        self.assertIn('/#/event/event',photo.call_args.args[1])
                    sql,args=next(q for q in queries if q[0].startswith('SELECT * FROM annha.media_assets'))
                    self.assertIn('camera_id=%s',sql);self.assertIn('event_id=%s',sql)
                    self.assertEqual(args,('home','event','camera'))

    def test_no_image_no_consent_or_revoked_consent_sends_text(self):
        for channel in ('email','telegram'):
            for options in ({'image':False},{'consent':False},{'revoke':True},
                            {'read_result':(None,'unavailable')}):
                with self.subTest(channel=channel,options=options):
                    mail,photo,text,updates,queries,state=self.run_delivery(channel,**options)
                    self.assertEqual(state,'accepted');photo.assert_not_called()
                    if channel=='email': self.assertNotIn('attachment',mail.call_args.kwargs)
                    else: self.assertEqual(text.call_count,1)

    def test_delay_and_telegram_rejection_and_ambiguous_timeout(self):
        mail,photo,text,updates,queries,state=self.run_delivery(age=0,image=False)
        self.assertEqual(state,'pending');self.assertEqual(updates,[])
        mail.assert_not_called();photo.assert_not_called();text.assert_not_called()
        self.assertTrue(any('next_attempt_at=%s' in sql for sql,args in queries))
        mail,photo,text,updates,queries,state=self.run_delivery(reject=True)
        self.assertEqual(state,'accepted');self.assertEqual(text.call_count,1)
        self.assertEqual(updates[0][-2],'text_fallback')
        mail,photo,text,updates,queries,state=self.run_delivery(ambiguous=True)
        self.assertEqual(state,'unknown');self.assertEqual(photo.call_count,1);text.assert_not_called()

    def test_configured_wait_covers_cloud_processing_and_keeps_fallback_deadline(self):
        mail,photo,text,updates,queries,state=self.run_delivery('email',age=4.3,image=False,wait_seconds=8)
        self.assertEqual(state,'pending');mail.assert_not_called();self.assertEqual(updates,[])
        mail,photo,text,updates,queries,state=self.run_delivery('email',age=4.3,image=True,wait_seconds=8)
        self.assertEqual(state,'accepted');self.assertEqual(mail.call_count,1)
        self.assertIn('attachment',mail.call_args.kwargs)
        mail,photo,text,updates,queries,state=self.run_delivery('email',age=9,image=False,wait_seconds=8)
        self.assertEqual(state,'accepted');self.assertEqual(mail.call_count,1)
        self.assertNotIn('attachment',mail.call_args.kwargs)

    def test_recipient_without_camera_access_gets_nothing(self):
        mail,photo,text,updates,queries,state=self.run_delivery(eligible=False)
        self.assertEqual(state,'cancelled')
        mail.assert_not_called();photo.assert_not_called();text.assert_not_called()

    def test_expired_demo_and_invalid_image_rejected(self):
        from unittest.mock import patch
        row={'status':'ready','expires_at':db.now()-services.timedelta(seconds=1),
             'mime_type':'image/png','size_bytes':20,'provider':'local','camera_id':'fixture'}
        with patch.object(services,'demo_camera',return_value=False):
            self.assertEqual(services._read_notification_image(row),(None,'missing'))
            row.update(expires_at=None,upload_key='demo:snapshot')
            with patch.object(services.media_storage,'LocalStorage') as storage:
                self.assertEqual(services._read_notification_image(row),(None,'missing'))
                storage.assert_not_called()
            row.update(upload_key='fixture',mime_type='text/plain')
            self.assertEqual(services._read_notification_image(row),(None,'unavailable'))
