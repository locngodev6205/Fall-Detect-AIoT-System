-- Preserve the existing app role and RLS boundary. Schedule permission may
-- create only TTS assets; uploaded audio remains restricted to audio permission.
BEGIN;
DROP POLICY audio_upload ON annha.media_assets;
CREATE POLICY audio_upload ON annha.media_assets FOR INSERT TO annha_app WITH CHECK (
  (
    (kind='audio' AND annha_private.can_camera(home_id,camera_id,'audio'))
    OR
    (kind='tts' AND (annha_private.can_camera(home_id,camera_id,'audio') OR annha_private.can_camera(home_id,camera_id,'schedules')))
  )
  AND status IN ('uploading','processing')
  AND created_by=annha_private.context_id('app.user_id')
);
COMMIT;
