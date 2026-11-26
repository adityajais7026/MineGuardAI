-- Generated from the SQLAlchemy models (postgresql dialect).
-- Creates every table that database/schema.sql does not. Idempotent: IF NOT EXISTS everywhere.
-- Run AFTER database/schema.sql. Safe to re-run.

CREATE TABLE IF NOT EXISTS audit_events (
	id VARCHAR(36) NOT NULL, 
	seq INTEGER NOT NULL, 
	actor_id VARCHAR(36), 
	actor_role VARCHAR(40), 
	action VARCHAR(100) NOT NULL, 
	entity_type VARCHAR(60) NOT NULL, 
	entity_id VARCHAR(36), 
	mine_id VARCHAR(36), 
	payload_json JSON, 
	prev_hash VARCHAR(64), 
	event_hash VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_audit_events_actor_id ON audit_events (actor_id);
CREATE INDEX IF NOT EXISTS ix_audit_events_entity_id ON audit_events (entity_id);
CREATE INDEX IF NOT EXISTS ix_audit_events_mine_id ON audit_events (mine_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_audit_events_seq ON audit_events (seq);

CREATE TABLE IF NOT EXISTS contractors (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	contact_person VARCHAR(255), 
	phone VARCHAR(15), 
	email VARCHAR(255), 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_contractors_is_active ON contractors (is_active);

CREATE TABLE IF NOT EXISTS emergency_events (
	id VARCHAR(36) NOT NULL, 
	mine_id VARCHAR(36) NOT NULL, 
	emergency_type VARCHAR(40) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	description TEXT, 
	latitude FLOAT, 
	longitude FLOAT, 
	location_text VARCHAR(500), 
	reported_by_id VARCHAR(36), 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_emergency_severity CHECK (severity IN ('low','medium','high','critical')), 
	CONSTRAINT ck_emergency_status CHECK (status IN ('open','responding','resolved','closed')), 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE, 
	FOREIGN KEY(reported_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_emergency_events_mine_id ON emergency_events (mine_id);
CREATE INDEX IF NOT EXISTS ix_emergency_events_status ON emergency_events (status);

CREATE TABLE IF NOT EXISTS geofences (
	id VARCHAR(36) NOT NULL, 
	mine_id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	boundary_type VARCHAR(20) NOT NULL, 
	center_lat FLOAT, 
	center_lng FLOAT, 
	radius_m FLOAT, 
	polygon_json JSON, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_geofence_type CHECK (boundary_type IN ('radius','polygon')), 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_geofences_mine_id ON geofences (mine_id);

CREATE TABLE IF NOT EXISTS inspection_templates (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	description TEXT, 
	inspection_type VARCHAR(50) NOT NULL, 
	mine_id VARCHAR(36), 
	regulatory_reference VARCHAR(500), 
	is_active BOOLEAN NOT NULL, 
	created_by_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE, 
	FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_inspection_templates_is_active ON inspection_templates (is_active);
CREATE INDEX IF NOT EXISTS ix_inspection_templates_mine_id ON inspection_templates (mine_id);

CREATE TABLE IF NOT EXISTS notifications (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36), 
	mine_id VARCHAR(36), 
	category VARCHAR(40) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	body TEXT, 
	severity VARCHAR(20) NOT NULL, 
	entity_type VARCHAR(60), 
	entity_id VARCHAR(36), 
	dedupe_key VARCHAR(200), 
	read_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_notifications_category ON notifications (category);
CREATE UNIQUE INDEX IF NOT EXISTS ix_notifications_dedupe_key ON notifications (dedupe_key);
CREATE INDEX IF NOT EXISTS ix_notifications_mine_id ON notifications (mine_id);
CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications (user_id);

CREATE TABLE IF NOT EXISTS risk_scores (
	id VARCHAR(36) NOT NULL, 
	mine_id VARCHAR(36) NOT NULL, 
	score FLOAT NOT NULL, 
	band VARCHAR(20) NOT NULL, 
	factors_json JSON, 
	computed_by VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_risk_band CHECK (band IN ('low','medium','high','critical')), 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_risk_scores_mine_id ON risk_scores (mine_id);

CREATE TABLE IF NOT EXISTS sensor_devices (
	id VARCHAR(36) NOT NULL, 
	mine_id VARCHAR(36) NOT NULL, 
	device_code VARCHAR(50) NOT NULL, 
	parameter VARCHAR(50) NOT NULL, 
	unit VARCHAR(20) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	location_text VARCHAR(500), 
	warning_threshold FLOAT, 
	critical_threshold FLOAT, 
	is_active BOOLEAN NOT NULL, 
	last_seen_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_sensor_source CHECK (source IN ('real','demo')), 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE, 
	UNIQUE (device_code)
);

CREATE INDEX IF NOT EXISTS ix_sensor_devices_mine_id ON sensor_devices (mine_id);

CREATE TABLE IF NOT EXISTS shifts (
	id VARCHAR(36) NOT NULL, 
	mine_id VARCHAR(36) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ends_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_by_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE, 
	FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_shifts_mine_id ON shifts (mine_id);

CREATE TABLE IF NOT EXISTS sync_records (
	id VARCHAR(36) NOT NULL, 
	client_guid VARCHAR(64) NOT NULL, 
	user_id VARCHAR(36), 
	mine_id VARCHAR(36), 
	entity_type VARCHAR(60) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	payload JSON, 
	result_ref_id VARCHAR(36), 
	error TEXT, 
	synced_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_sync_records_client_guid ON sync_records (client_guid);
CREATE INDEX IF NOT EXISTS ix_sync_records_mine_id ON sync_records (mine_id);
CREATE INDEX IF NOT EXISTS ix_sync_records_user_id ON sync_records (user_id);

CREATE TABLE IF NOT EXISTS workers (
	id VARCHAR(36) NOT NULL, 
	mine_id VARCHAR(36) NOT NULL, 
	contractor_id VARCHAR(36), 
	employee_code VARCHAR(50) NOT NULL, 
	full_name VARCHAR(255) NOT NULL, 
	role VARCHAR(100), 
	phone VARCHAR(15), 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE, 
	FOREIGN KEY(contractor_id) REFERENCES contractors (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_workers_contractor_id ON workers (contractor_id);
CREATE INDEX IF NOT EXISTS ix_workers_is_active ON workers (is_active);
CREATE INDEX IF NOT EXISTS ix_workers_mine_id ON workers (mine_id);

CREATE TABLE IF NOT EXISTS attendance (
	id VARCHAR(36) NOT NULL, 
	shift_id VARCHAR(36), 
	worker_id VARCHAR(36) NOT NULL, 
	mine_id VARCHAR(36) NOT NULL, 
	check_in_at TIMESTAMP WITH TIME ZONE, 
	check_out_at TIMESTAMP WITH TIME ZONE, 
	verification VARCHAR(20) NOT NULL, 
	check_in_lat FLOAT, 
	check_in_lng FLOAT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_attendance_verification CHECK (verification IN ('manual','qr','geofence','biometric')), 
	FOREIGN KEY(shift_id) REFERENCES shifts (id) ON DELETE SET NULL, 
	FOREIGN KEY(worker_id) REFERENCES workers (id) ON DELETE CASCADE, 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_attendance_mine_id ON attendance (mine_id);
CREATE INDEX IF NOT EXISTS ix_attendance_shift_id ON attendance (shift_id);
CREATE INDEX IF NOT EXISTS ix_attendance_worker_id ON attendance (worker_id);

CREATE TABLE IF NOT EXISTS compliance_requirements (
	id VARCHAR(36) NOT NULL, 
	mine_id VARCHAR(36), 
	title VARCHAR(255) NOT NULL, 
	description TEXT, 
	reference VARCHAR(500) NOT NULL, 
	frequency VARCHAR(20) NOT NULL, 
	template_id VARCHAR(36), 
	due_day INTEGER, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_comp_req_frequency CHECK (frequency IN ('daily','weekly','monthly','quarterly','custom')), 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE, 
	FOREIGN KEY(template_id) REFERENCES inspection_templates (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_compliance_requirements_is_active ON compliance_requirements (is_active);
CREATE INDEX IF NOT EXISTS ix_compliance_requirements_mine_id ON compliance_requirements (mine_id);

CREATE TABLE IF NOT EXISTS contractor_documents (
	id VARCHAR(36) NOT NULL, 
	contractor_id VARCHAR(36), 
	worker_id VARCHAR(36), 
	mine_id VARCHAR(36), 
	doc_type VARCHAR(80) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	document_ref VARCHAR(500) NOT NULL, 
	issued_on TIMESTAMP WITH TIME ZONE, 
	expires_on TIMESTAMP WITH TIME ZONE, 
	verification_status VARCHAR(30) NOT NULL, 
	verified_by_id VARCHAR(36), 
	notes TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(contractor_id) REFERENCES contractors (id) ON DELETE CASCADE, 
	FOREIGN KEY(worker_id) REFERENCES workers (id) ON DELETE CASCADE, 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE, 
	FOREIGN KEY(verified_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_contractor_documents_contractor_id ON contractor_documents (contractor_id);
CREATE INDEX IF NOT EXISTS ix_contractor_documents_mine_id ON contractor_documents (mine_id);
CREATE INDEX IF NOT EXISTS ix_contractor_documents_worker_id ON contractor_documents (worker_id);

CREATE TABLE IF NOT EXISTS inspection_template_items (
	id VARCHAR(36) NOT NULL, 
	template_id VARCHAR(36) NOT NULL, 
	position INTEGER NOT NULL, 
	label VARCHAR(500) NOT NULL, 
	description TEXT, 
	category VARCHAR(50) NOT NULL, 
	result_options VARCHAR(200) NOT NULL, 
	severity_weight INTEGER NOT NULL, 
	requires_evidence BOOLEAN NOT NULL, 
	options_json JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(template_id) REFERENCES inspection_templates (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_inspection_template_items_template_id ON inspection_template_items (template_id);

CREATE TABLE IF NOT EXISTS telemetry_readings (
	id VARCHAR(36) NOT NULL, 
	device_id VARCHAR(36) NOT NULL, 
	mine_id VARCHAR(36) NOT NULL, 
	value FLOAT NOT NULL, 
	unit VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_telemetry_status CHECK (status IN ('normal','warning','critical','unknown')), 
	FOREIGN KEY(device_id) REFERENCES sensor_devices (id) ON DELETE CASCADE, 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_telemetry_readings_device_id ON telemetry_readings (device_id);
CREATE INDEX IF NOT EXISTS ix_telemetry_readings_mine_id ON telemetry_readings (mine_id);
CREATE INDEX IF NOT EXISTS ix_telemetry_readings_recorded_at ON telemetry_readings (recorded_at);

CREATE TABLE IF NOT EXISTS compliance_assessments (
	id VARCHAR(36) NOT NULL, 
	requirement_id VARCHAR(36) NOT NULL, 
	mine_id VARCHAR(36), 
	status VARCHAR(20) NOT NULL, 
	period_start TIMESTAMP WITH TIME ZONE NOT NULL, 
	period_end TIMESTAMP WITH TIME ZONE NOT NULL, 
	inspection_id VARCHAR(36), 
	notes TEXT, 
	assessed_by_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_comp_assess_status CHECK (status IN ('compliant','attention','violation','not_assessed')), 
	FOREIGN KEY(requirement_id) REFERENCES compliance_requirements (id) ON DELETE CASCADE, 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE, 
	FOREIGN KEY(inspection_id) REFERENCES inspections (id) ON DELETE SET NULL, 
	FOREIGN KEY(assessed_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_compliance_assessments_mine_id ON compliance_assessments (mine_id);
CREATE INDEX IF NOT EXISTS ix_compliance_assessments_requirement_id ON compliance_assessments (requirement_id);

CREATE TABLE IF NOT EXISTS inspection_checklist_items (
	id VARCHAR(36) NOT NULL, 
	inspection_id VARCHAR(36) NOT NULL, 
	template_item_id VARCHAR(36), 
	position INTEGER NOT NULL, 
	label VARCHAR(500) NOT NULL, 
	category VARCHAR(50) NOT NULL, 
	result_options VARCHAR(200) NOT NULL, 
	severity_weight INTEGER NOT NULL, 
	result VARCHAR(20), 
	comment TEXT, 
	ai_suggestion VARCHAR(20), 
	ai_confidence FLOAT, 
	ai_model VARCHAR(255), 
	ai_confirmed_by_id VARCHAR(36), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_checklist_result CHECK (result IS NULL OR result IN ('pass','fail','na','unknown')), 
	CONSTRAINT ck_checklist_ai_suggestion CHECK (ai_suggestion IS NULL OR ai_suggestion IN ('pass','fail','na','unknown')), 
	FOREIGN KEY(inspection_id) REFERENCES inspections (id) ON DELETE CASCADE, 
	FOREIGN KEY(template_item_id) REFERENCES inspection_template_items (id) ON DELETE SET NULL, 
	FOREIGN KEY(ai_confirmed_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_inspection_checklist_items_inspection_id ON inspection_checklist_items (inspection_id);

CREATE TABLE IF NOT EXISTS evidence (
	id VARCHAR(36) NOT NULL, 
	mine_id VARCHAR(36), 
	kind VARCHAR(40) NOT NULL, 
	inspection_id VARCHAR(36), 
	checklist_item_id VARCHAR(36), 
	incident_id VARCHAR(36), 
	corrective_action_id VARCHAR(36), 
	camera_event_id VARCHAR(36), 
	emergency_id VARCHAR(36), 
	media_type VARCHAR(20) NOT NULL, 
	file_path VARCHAR(500) NOT NULL, 
	original_filename VARCHAR(255), 
	mime_type VARCHAR(100), 
	size_bytes INTEGER, 
	sha256 VARCHAR(64), 
	description TEXT, 
	uploaded_by_id VARCHAR(36), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_evidence_media_type CHECK (media_type IN ('image','video','audio','document')), 
	FOREIGN KEY(mine_id) REFERENCES mines (id) ON DELETE CASCADE, 
	FOREIGN KEY(inspection_id) REFERENCES inspections (id) ON DELETE CASCADE, 
	FOREIGN KEY(checklist_item_id) REFERENCES inspection_checklist_items (id) ON DELETE CASCADE, 
	FOREIGN KEY(incident_id) REFERENCES incidents (id) ON DELETE CASCADE, 
	FOREIGN KEY(corrective_action_id) REFERENCES corrective_actions (id) ON DELETE CASCADE, 
	FOREIGN KEY(camera_event_id) REFERENCES camera_events (id) ON DELETE CASCADE, 
	FOREIGN KEY(emergency_id) REFERENCES emergency_events (id) ON DELETE CASCADE, 
	FOREIGN KEY(uploaded_by_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_evidence_corrective_action_id ON evidence (corrective_action_id);
CREATE INDEX IF NOT EXISTS ix_evidence_incident_id ON evidence (incident_id);
CREATE INDEX IF NOT EXISTS ix_evidence_inspection_id ON evidence (inspection_id);
CREATE INDEX IF NOT EXISTS ix_evidence_kind ON evidence (kind);
CREATE INDEX IF NOT EXISTS ix_evidence_mine_id ON evidence (mine_id);
