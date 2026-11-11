-- Run on an already migrated database with the backend login (or SET ROLE locally).
-- All probe rows are rolled back. Sequence values may advance.
BEGIN;
INSERT INTO twinsight.catalog_records(record_id,kind,title,owner,data_origin,status,details,fingerprint,created_at)
VALUES ('__governance_probe__','detection','probe','test','synthetic','draft','{}',repeat('a',64),now());
UPDATE twinsight.catalog_records SET title=title WHERE record_id='__governance_probe__';
DO $$ BEGIN
 IF (SELECT count(*) FROM twinsight.catalog_audit WHERE record_key='__governance_probe__') <> 1 THEN
   RAISE EXCEPTION 'No-op update must not add audit rows';
 END IF;
END $$;
UPDATE twinsight.catalog_records SET title='changed' WHERE record_id='__governance_probe__';
INSERT INTO twinsight.catalog_logs(record_id,stream,line_no,message)
VALUES ('__governance_probe__','detections.jsonl-probe',1,'{"camera_id":"probe","width":720,"height":480}');
INSERT INTO twinsight.calibration_versions(calibration_id,camera_id,version,image_width,image_height,coordinate_system,parameters,source_sha256)
VALUES ('__calibration_probe__','probe','test',720,480,'unity_xz_m','{}',repeat('a',64));
DO $$ BEGIN
 BEGIN
   INSERT INTO twinsight.experiment_bindings(record_id,stream,experiment_id,camera_id,image_width,image_height,calibration_id)
   VALUES ('__governance_probe__','detections.jsonl-probe','__governance_probe__','wrong',720,480,'__calibration_probe__');
   RAISE EXCEPTION 'Camera mismatch was accepted';
 EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN
   INSERT INTO twinsight.experiment_bindings(record_id,stream,experiment_id,camera_id,image_width,image_height)
   VALUES ('__governance_probe__','detections.jsonl-probe','__governance_probe__','probe',1440,960);
   RAISE EXCEPTION 'Resolution mismatch was accepted';
 EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN
   DELETE FROM twinsight.catalog_audit WHERE record_key='__governance_probe__';
   RAISE EXCEPTION 'Audit deletion was permitted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
   UPDATE twinsight.calibration_versions SET version='changed' WHERE calibration_id='__calibration_probe__';
   RAISE EXCEPTION 'Version mutation was permitted';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
INSERT INTO twinsight.experiment_bindings(record_id,stream,experiment_id,camera_id,image_width,image_height,calibration_id)
VALUES ('__governance_probe__','detections.jsonl-probe','__governance_probe__','probe',720,480,'__calibration_probe__');
DO $$ BEGIN
 IF (SELECT count(*) FROM twinsight.catalog_audit WHERE record_key='__governance_probe__') <> 3 THEN
   RAISE EXCEPTION 'Record and binding audit missing';
 END IF;
 IF EXISTS (SELECT 1 FROM twinsight.catalog_audit WHERE record_key='__governance_probe__' AND database_actor<>session_user) THEN
   RAISE EXCEPTION 'Wrong audit actor';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM twinsight.catalog_audit WHERE record_key='__governance_probe__' AND operation='UPDATE'
   AND before_data::jsonb->>'title'='probe' AND after_data::jsonb->>'title'='changed') THEN
   RAISE EXCEPTION 'Before/after audit missing';
 END IF;
 IF has_table_privilege('anon','twinsight.catalog_audit','SELECT') OR has_table_privilege('authenticated','twinsight.calibration_versions','SELECT') THEN
   RAISE EXCEPTION 'Private metadata exposed';
 END IF;
END $$;
ROLLBACK;
