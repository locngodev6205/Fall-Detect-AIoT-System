-- Atomically add a TTS job while the app transaction writes its reminder revision.
-- This is additive and does not modify existing rows or media.
BEGIN;
CREATE FUNCTION annha_private.enqueue_tts(
 target_home uuid,
 target_camera uuid,
 target_reminder uuid,
 target_version integer,
 target_asset uuid,
 encrypted_text bytea,
 encryption_key_id text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF annha_private.context_id('app.home_id') IS DISTINCT FROM target_home
    OR NOT annha_private.can_camera(target_home,target_camera,'schedules') THEN
  RAISE EXCEPTION 'TTS schedule permission denied' USING ERRCODE='42501';
 END IF;
 IF NOT EXISTS (
  SELECT 1 FROM annha.reminders r
  JOIN annha.reminder_revisions v ON v.home_id=r.home_id AND v.camera_id=r.camera_id AND v.reminder_id=r.id
  JOIN annha.media_assets a ON a.home_id=r.home_id AND a.camera_id=r.camera_id AND a.id=v.asset_id
  WHERE r.home_id=target_home AND r.camera_id=target_camera AND r.id=target_reminder
    AND r.current_version=target_version AND v.version=target_version AND v.source='tts'
    AND a.id=target_asset AND a.status='processing'
 ) THEN
  RAISE EXCEPTION 'TTS revision is not current' USING ERRCODE='23514';
 END IF;
 INSERT INTO annha_private.job_queue(home_id,kind,asset_id,payload,secret_ciphertext,key_id,idempotency_key)
 VALUES(target_home,'tts',target_asset,jsonb_build_object('camera_id',target_camera),encrypted_text,
        encryption_key_id,'tts:'||target_asset::text)
 ON CONFLICT(idempotency_key) DO NOTHING;
END
$$;
REVOKE ALL ON FUNCTION annha_private.enqueue_tts(uuid,uuid,uuid,integer,uuid,bytea,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION annha_private.enqueue_tts(uuid,uuid,uuid,integer,uuid,bytea,text) TO annha_app;
COMMIT;
