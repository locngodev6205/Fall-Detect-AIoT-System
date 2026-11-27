-- Run with psql -v ON_ERROR_STOP=1 -v home=UUID -v camera=UUID -v remove=false.
-- Specify remove=true to delete only this tool's synthetic batches for the exact camera.
BEGIN;
SELECT EXISTS (
 SELECT 1 FROM annha.cameras WHERE home_id=:'home'::uuid AND id=:'camera'::uuid
 AND retired_at IS NULL
) AS camera_matches \gset
\if :camera_matches
SELECT pg_advisory_xact_lock(hashtextextended('sim-env-v1:' || :'camera', 0));
\if :remove
DELETE FROM annha.telemetry_batches
WHERE home_id=:'home'::uuid AND camera_id=:'camera'::uuid AND message_id LIKE 'sim-env-v1:%';
\else
WITH slots AS (
 SELECT stamp, stamp AT TIME ZONE 'Asia/Ho_Chi_Minh' AS local_stamp
 FROM generate_series('2026-11-20 00:00+07'::timestamptz,
   LEAST(now(), '2026-11-28 00:00+07'::timestamptz - interval '15 minutes'), interval '15 minutes') stamp
 WHERE NOT EXISTS (
  SELECT 1 FROM annha.telemetry_batches b
  WHERE b.home_id=:'home'::uuid AND b.camera_id=:'camera'::uuid
    AND b.observed_at>=stamp AND b.observed_at<stamp+interval '15 minutes'
    AND b.message_id NOT LIKE 'sim-env-v1:%'
 )
), inserted AS (
 INSERT INTO annha.telemetry_batches(home_id,camera_id,message_id,observed_at)
 SELECT :'home'::uuid, :'camera'::uuid, 'sim-env-v1:' || extract(epoch FROM stamp)::bigint, stamp
 FROM slots ON CONFLICT(camera_id,message_id) DO NOTHING
 RETURNING id,home_id,camera_id,observed_at
), readings AS (
 INSERT INTO annha.sensor_readings(home_id,camera_id,batch_id,metric,value,unit,quality)
 SELECT b.home_id,b.camera_id,b.id,m.metric,m.value,m.unit,'valid'
 FROM inserted b JOIN slots s ON b.observed_at=s.stamp
 CROSS JOIN LATERAL (SELECT
   cos(2*pi()*(extract(hour FROM s.local_stamp)+extract(minute FROM s.local_stamp)/60-14)/24) AS day,
   sin(extract(doy FROM s.local_stamp)*1.618) AS variation,
   (('x'||substr(md5('annha-27:'||extract(epoch FROM s.stamp)::text),1,4))::bit(16)::int / 65535.0 - 0.5) AS noise
 ) d
 CROSS JOIN LATERAL (VALUES
   ('temperature', round((27.7 + 3.6*d.day + 0.8*d.variation + 0.6*d.noise)::numeric,1), 'C'),
   ('humidity', round((75.0 - 10.0*d.day - 3.0*d.variation + 2.0*d.noise)::numeric,1), '%'),
   ('gas', round((185 + 13*d.day + 12*d.variation + 9*d.noise)::numeric), 'ADC')
 ) m(metric,value,unit)
 RETURNING batch_id
)
SELECT count(DISTINCT batch_id) AS added_batches,count(*) AS added_readings FROM readings;
\endif
COMMIT;
\else
ROLLBACK;
\warn Camera ID/Home ID do not match an active camera; nothing changed.
\quit
\endif
