-- Extend annha.commands kind CHECK constraint to support manual Web PTZ commands.
BEGIN;
ALTER TABLE annha.commands
 DROP CONSTRAINT commands_kind_check;
ALTER TABLE annha.commands
 ADD CONSTRAINT commands_kind_check CHECK (kind IN ('play_audio','test_speaker','silence','ptz_move','ptz_center'));
COMMIT;
