-- Apply once after twinsight_schema.sql as the project DB owner.
-- This is a backend-only group role. It cannot log in or bypass RLS.
CREATE ROLE twinsight_backend NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA twinsight TO twinsight_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA twinsight TO twinsight_backend;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA twinsight TO twinsight_backend;

-- Backend services are authorized for all project rows. This is intentionally
-- NOT a grant/policy for browser anon/authenticated users.
DO $$
DECLARE item record;
BEGIN
    FOR item IN SELECT tablename FROM pg_tables WHERE schemaname = 'twinsight'
    LOOP
        EXECUTE format(
            'CREATE POLICY backend_access ON twinsight.%I FOR ALL TO twinsight_backend USING (true) WITH CHECK (true)',
            item.tablename
        );
    END LOOP;
END $$;

-- Constraints mirror the existing backend's input validation.
ALTER TABLE twinsight.frames ADD CONSTRAINT ck_frames_shape
    CHECK (frame_no >= 0 AND width > 0 AND height > 0);
ALTER TABLE twinsight.map_references ADD CONSTRAINT ck_map_reference_range
    CHECK (origin_lat > -85 AND origin_lat < 85 AND origin_lon >= -180 AND origin_lon <= 180);
ALTER TABLE twinsight.alerts ADD CONSTRAINT ck_alert_status
    CHECK (status IN ('unconfirmed', 'confirmed', 'dismissed'));

-- Camera history and latest-frame queries, in addition to existing run indexes.
CREATE INDEX ix_alerts_camera_timestamp ON twinsight.alerts (camera_id, timestamp DESC, id DESC);
CREATE INDEX ix_frames_run_received ON twinsight.frames (run_id, received_at DESC, id DESC);

-- These defaults apply to future owner-created objects in this app schema.
-- Future tables still require their own reviewed grants and RLS policies.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA twinsight
    REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA twinsight
    REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
-- PostgreSQL grants function EXECUTE to PUBLIC globally by default.
-- A schema-level default REVOKE cannot override that global grant.
-- Revoke EXECUTE explicitly for every future function before exposing it.
-- Schema USAGE remains denied to browser roles.
