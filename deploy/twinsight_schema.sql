-- TwinSight initial DB schema; generated from existing SQLAlchemy models.

-- Private backend access only; no browser grants.

CREATE SCHEMA twinsight;

REVOKE ALL ON SCHEMA twinsight FROM PUBLIC, anon, authenticated;

CREATE TABLE twinsight.cameras (
	camera_id VARCHAR NOT NULL,
	name VARCHAR,
	source VARCHAR DEFAULT 'unknown' NOT NULL,
	lat FLOAT,
	lon FLOAT,
	stream_url TEXT,
	stream_fetched_at TIMESTAMP WITH TIME ZONE,
	image_width INTEGER,
	image_height INTEGER,
	is_ptz BOOLEAN DEFAULT false NOT NULL,
	status VARCHAR DEFAULT 'unknown' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (camera_id)
);

ALTER TABLE twinsight.cameras ENABLE ROW LEVEL SECURITY;

CREATE TABLE twinsight.runs (
	run_id VARCHAR NOT NULL,
	camera_id VARCHAR NOT NULL,
	timestamp_kind VARCHAR,
	started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (run_id),
	FOREIGN KEY(camera_id) REFERENCES twinsight.cameras (camera_id)
);

CREATE INDEX ix_map_runs_camera_started ON twinsight.runs (camera_id, started_at);

ALTER TABLE twinsight.runs ENABLE ROW LEVEL SECURITY;

CREATE TABLE twinsight.alerts (
	id SERIAL NOT NULL,
	run_id VARCHAR NOT NULL,
	alert_id VARCHAR NOT NULL,
	camera_id VARCHAR NOT NULL,
	frame_no INTEGER NOT NULL,
	timestamp FLOAT NOT NULL,
	type VARCHAR NOT NULL,
	severity VARCHAR NOT NULL,
	status VARCHAR DEFAULT 'unconfirmed' NOT NULL,
	message TEXT NOT NULL,
	evidence JSON DEFAULT '[]'::json NOT NULL,
	basis TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	handled_by VARCHAR,
	PRIMARY KEY (id),
	CONSTRAINT uq_alerts_run_alert UNIQUE (run_id, alert_id),
	FOREIGN KEY(run_id) REFERENCES twinsight.runs (run_id)
);

CREATE INDEX ix_map_alerts_run_timestamp ON twinsight.alerts (run_id, timestamp);

ALTER TABLE twinsight.alerts ENABLE ROW LEVEL SECURITY;

CREATE TABLE twinsight.catalog_records (
	record_id VARCHAR(128) NOT NULL,
	kind VARCHAR(32) NOT NULL,
	title VARCHAR(256) NOT NULL,
	owner VARCHAR(128) NOT NULL,
	data_origin VARCHAR(32) NOT NULL,
	status VARCHAR(32) NOT NULL,
	camera_id VARCHAR,
	detection_run_id VARCHAR,
	details JSON NOT NULL,
	fingerprint VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (record_id),
	FOREIGN KEY(detection_run_id) REFERENCES twinsight.runs (run_id),
	FOREIGN KEY(camera_id) REFERENCES twinsight.cameras (camera_id)
);

CREATE INDEX ix_twinsight_catalog_records_camera_id ON twinsight.catalog_records (camera_id);

CREATE INDEX ix_twinsight_catalog_records_data_origin ON twinsight.catalog_records (data_origin);

CREATE INDEX ix_twinsight_catalog_records_detection_run_id ON twinsight.catalog_records (detection_run_id);

CREATE INDEX ix_twinsight_catalog_records_kind ON twinsight.catalog_records (kind);

ALTER TABLE twinsight.catalog_records ENABLE ROW LEVEL SECURITY;

CREATE TABLE twinsight.frames (
	id SERIAL NOT NULL,
	run_id VARCHAR NOT NULL,
	frame_no INTEGER NOT NULL,
	timestamp FLOAT NOT NULL,
	timestamp_kind VARCHAR NOT NULL,
	received_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	width INTEGER NOT NULL,
	height INTEGER NOT NULL,
	image_path TEXT,
	inference_ms FLOAT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(run_id) REFERENCES twinsight.runs (run_id),
	CONSTRAINT uq_frames_run_frame UNIQUE (run_id, frame_no)
);

ALTER TABLE twinsight.frames ENABLE ROW LEVEL SECURITY;

CREATE TABLE twinsight.map_references (
	run_id VARCHAR NOT NULL,
	origin_lat FLOAT NOT NULL,
	origin_lon FLOAT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (run_id),
	FOREIGN KEY(run_id) REFERENCES twinsight.runs (run_id)
);

ALTER TABLE twinsight.map_references ENABLE ROW LEVEL SECURITY;

CREATE TABLE twinsight.alert_history (
	id SERIAL NOT NULL,
	alert_id INTEGER NOT NULL,
	old_status VARCHAR NOT NULL,
	new_status VARCHAR NOT NULL,
	old_handled_by VARCHAR,
	handled_by VARCHAR,
	changed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(alert_id) REFERENCES twinsight.alerts (id)
);

CREATE INDEX ix_twinsight_alert_history_alert_id ON twinsight.alert_history (alert_id);

ALTER TABLE twinsight.alert_history ENABLE ROW LEVEL SECURITY;

CREATE TABLE twinsight.catalog_files (
	id SERIAL NOT NULL,
	record_id VARCHAR(128) NOT NULL,
	path VARCHAR(512) NOT NULL,
	size_bytes BIGINT NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	role VARCHAR(64) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(record_id) REFERENCES twinsight.catalog_records (record_id),
	CONSTRAINT uq_catalog_file_path UNIQUE (record_id, path)
);

CREATE INDEX ix_twinsight_catalog_files_record_id ON twinsight.catalog_files (record_id);

ALTER TABLE twinsight.catalog_files ENABLE ROW LEVEL SECURITY;

CREATE TABLE twinsight.catalog_logs (
	id SERIAL NOT NULL,
	record_id VARCHAR(128) NOT NULL,
	stream VARCHAR(128) NOT NULL,
	line_no INTEGER NOT NULL,
	message TEXT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_catalog_log_line UNIQUE (record_id, stream, line_no),
	FOREIGN KEY(record_id) REFERENCES twinsight.catalog_records (record_id)
);

CREATE INDEX ix_twinsight_catalog_logs_record_id ON twinsight.catalog_logs (record_id);

ALTER TABLE twinsight.catalog_logs ENABLE ROW LEVEL SECURITY;

CREATE TABLE twinsight.catalog_parents (
	record_id VARCHAR(128) NOT NULL,
	parent_id VARCHAR(128) NOT NULL,
	PRIMARY KEY (record_id, parent_id),
	FOREIGN KEY(record_id) REFERENCES twinsight.catalog_records (record_id),
	FOREIGN KEY(parent_id) REFERENCES twinsight.catalog_records (record_id)
);

CREATE INDEX ix_twinsight_catalog_parents_parent_id ON twinsight.catalog_parents (parent_id);

ALTER TABLE twinsight.catalog_parents ENABLE ROW LEVEL SECURITY;

CREATE TABLE twinsight.detections (
	id SERIAL NOT NULL,
	frame_id INTEGER NOT NULL,
	class_name VARCHAR NOT NULL,
	class_id INTEGER NOT NULL,
	category_id INTEGER NOT NULL,
	model_id VARCHAR NOT NULL,
	track_id INTEGER,
	confidence FLOAT NOT NULL,
	x1 FLOAT NOT NULL,
	y1 FLOAT NOT NULL,
	x2 FLOAT NOT NULL,
	y2 FLOAT NOT NULL,
	ground_px_u FLOAT,
	ground_px_v FLOAT,
	mapped_x FLOAT,
	mapped_z FLOAT,
	PRIMARY KEY (id),
	FOREIGN KEY(frame_id) REFERENCES twinsight.frames (id)
);

CREATE INDEX ix_twinsight_detections_class_name ON twinsight.detections (class_name);

CREATE INDEX ix_twinsight_detections_frame_id ON twinsight.detections (frame_id);

ALTER TABLE twinsight.detections ENABLE ROW LEVEL SECURITY;

CREATE TABLE twinsight.detection_coordinates (
	detection_id INTEGER NOT NULL,
	raw_xz JSON,
	corrected_xz JSON,
	PRIMARY KEY (detection_id),
	FOREIGN KEY(detection_id) REFERENCES twinsight.detections (id) ON DELETE CASCADE
);

ALTER TABLE twinsight.detection_coordinates ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON ALL TABLES IN SCHEMA twinsight FROM PUBLIC, anon, authenticated;

REVOKE ALL ON ALL SEQUENCES IN SCHEMA twinsight FROM PUBLIC, anon, authenticated;
