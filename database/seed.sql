-- ============================================================================
-- MineGuardAI — Supabase PostgreSQL seed data (SIMULATED DEMO DATA)
-- ============================================================================
-- Everything in this file is synthetic demo data for development/demo
-- purposes. It does NOT represent real mines, sensors or government data.
--
-- Usage (Supabase SQL editor or psql), AFTER schema.sql:
--   psql "$DATABASE_URL" -f database/schema.sql
--   psql "$DATABASE_URL" -f database/seed.sql
--
-- The script is IDEMPOTENT (uses explicit UUIDs + ON CONFLICT DO NOTHING),
-- so re-running it will not duplicate rows.
-- Demo user passwords (bcrypt hashes of 'Admin@123' / 'Manager@123' /
-- 'Safety@123' / 'Env@123'):
--   admin@mineguard.ai      -> Admin@123    (admin)
--   manager@mineguard.ai    -> Manager@123  (mine_manager)
--   safety@mineguard.ai     -> Safety@123   (safety_officer)
--   env@mineguard.ai        -> Env@123      (environmental_officer)
-- CHANGE THESE BEFORE ANY REAL DEPLOYMENT.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1) Users (4 core roles)
-- ----------------------------------------------------------------------------
INSERT INTO users (id, email, full_name, role, hashed_password, is_active) VALUES
  ('u-admin-0001', 'admin@mineguard.ai',    'Asha Verma',    'admin',                 '$2b$12$8I0mZjgwmuhjEqqIK94/1.PUL0rrqbaa80yfMrMahmas3Yh1YPrMy', TRUE),
  ('u-mgr-0001',   'manager@mineguard.ai',  'Rohit Malhotra','mine_manager',          '$2b$12$EmXT31c.JC/UgOO836hk1e3YYzw/OVUmZ/fUTaWKxzKXcQExk.FNW', TRUE),
  ('u-safe-0001',  'safety@mineguard.ai',   'Priya Nair',    'safety_officer',        '$2b$12$YA4ZYaREkcnmct6eaFAFKuvD8GRZOtrZuCf/AVOf.21XOpRmanpFC', TRUE),
  ('u-env-0001',   'env@mineguard.ai',      'Karan Desai',   'environmental_officer', '$2b$12$VO6nAXbjaj2c3EpNaB22VexYGsgzslY8Qsjx6zneMN/aU4PMGfeOa', TRUE)
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 2) Mines (3 mines: operational, maintenance, suspended)
-- ----------------------------------------------------------------------------
INSERT INTO mines (id, name, code, mine_type, status, location, latitude, longitude, manager_id, description) VALUES
  ('m-iron-0001', 'Keonjhar Iron Ore Mine',   'MINE-KIR', 'open_cast',   'operational', 'Keonjhar, Odisha',        21.6289, 85.5846, 'u-mgr-0001', 'Simulated open-cast iron ore operation for demo purposes.'),
  ('m-coal-0002', 'Talcher Coal Mine',        'MINE-TCH', 'underground', 'maintenance', 'Talcher, Odisha',         20.9333, 85.2167, 'u-mgr-0001', 'Simulated underground coal operation (maintenance window).'),
  ('m-baux-0003', 'Damanjodi Bauxite Mine',   'MINE-DBX', 'mixed',       'suspended',   'Damanjodi, Odisha',       18.8000, 82.9000, 'u-mgr-0001', 'Simulated mixed bauxite site, temporarily suspended.')
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 3) Compliance rules (global defaults; thresholds illustrative only)
-- ----------------------------------------------------------------------------
INSERT INTO compliance_rules (id, name, description, parameter, operator, threshold, unit, severity, is_active, mine_id) VALUES
  ('r-pm25-0001', 'PM2.5 limit',         'PM2.5 must stay under 60 µg/m³ (simulated threshold).', 'pm2_5',      '>',  60.0,  'µg/m³', 'high',     TRUE, NULL),
  ('r-pm10-0002', 'PM10 limit',          'PM10 must stay under 100 µg/m³ (simulated threshold).', 'pm10',       '>',  100.0, 'µg/m³', 'high',     TRUE, NULL),
  ('r-noise-0003','Daytime noise limit', 'Noise above 85 dB breaches the simulated daytime limit.','noise',      '>',  85.0,  'dB',    'medium',   TRUE, NULL),
  ('r-temp-0004', 'Temperature extreme', 'Surface temperature above 45 °C (simulated threshold).', 'temperature','>',  45.0,  '°C',    'medium',   TRUE, NULL),
  ('r-co-0005',   'CO gas limit',        'Carbon monoxide above 30 ppm (simulated threshold).',    'co',         '>',  30.0,  'ppm',   'critical', TRUE, NULL),
  ('r-aqi-0006',  'Air quality index',   'AQI above 200 is a critical air-quality breach (simulated).','aqi',    '>',  200.0, 'index', 'critical', TRUE, NULL)
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 4) Restricted zones + assigned cameras
-- ----------------------------------------------------------------------------
INSERT INTO restricted_zones (id, mine_id, name, description, camera_id, is_active) VALUES
  ('z-blast-0001', 'm-iron-0001', 'Blast Zone A',        'Active blasting area — no entry without clearance.', 'CAM-KIR-01', TRUE),
  ('z-haul-0002',  'm-iron-0001', 'Haul Road Crossing',  'Heavy vehicle corridor; pedestrians prohibited.',    'CAM-KIR-02', TRUE),
  ('z-gas-0003',   'm-coal-0002', 'Gassy Panel 3',       'Underground panel with gas risk; authorised only.',  'CAM-TCH-01', TRUE),
  ('z-crush-0004', 'm-baux-0003', 'Crusher Bay',         'Crusher maintenance bay; entry during shutdown only.','CAM-DBX-01', TRUE)
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 5) Environmental readings: 14 days, 6 parameters, every 4 hours per mine
--    Generates ~1500 rows. status is precomputed to mirror what the backend
--    compliance engine would set ('normal' | 'violation').
-- ----------------------------------------------------------------------------
INSERT INTO environmental_readings (id, mine_id, parameter, value, unit, threshold, status, source, recorded_at)
SELECT
  'r-' || m.code || '-' || g.parameter || '-' || to_char(ts, 'YYYYMMDDHH24MI') AS id,
  m.id,
  g.parameter,
  round((base_val * (1 + ((hashval % 40) - 15) / 100.0))::numeric, 1) AS value,
  g.unit,
  g.thr,
  CASE WHEN base_val * (1 + ((hashval % 40) - 15) / 100.0) > g.thr
       THEN 'violation' ELSE 'normal' END AS status,
  'simulated',
  ts
FROM mines m
CROSS JOIN (VALUES
  ('pm2_5',       82.0, 60.0,  'µg/m³'),
  ('pm10',       130.0, 100.0, 'µg/m³'),
  ('noise',       78.0, 85.0,  'dB'),
  ('temperature', 36.0, 45.0,  '°C'),
  ('co',          18.0, 30.0,  'ppm'),
  ('aqi',        155.0, 200.0, 'index')
) AS g(parameter, base_val, thr, unit)
CROSS JOIN LATERAL (
  SELECT generate_series(
    (now() - interval '13 days')::timestamptz,
    now()::timestamptz,
    interval '4 hours'
  ) AS ts
) series
CROSS JOIN LATERAL (
  -- deterministic pseudo-random 0..N from md5 (bigint math avoids int4 overflow)
  SELECT abs(
    get_byte(d, 0)::bigint * 16777216 +
    get_byte(d, 1)::bigint * 65536 +
    get_byte(d, 2)::bigint * 256 +
    get_byte(d, 3)::bigint
  ) AS hashval
  FROM (SELECT decode(substr(md5(m.code || g.parameter || ts::text), 1, 8), 'hex') AS d) h1
) h
WHERE m.status <> 'closed'
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 6) Camera events (detection_source = 'simulated' — see honesty note above)
-- ----------------------------------------------------------------------------
INSERT INTO camera_events (id, mine_id, zone_id, camera_id, event_type, detected_object, zone_label, confidence, severity, status, detection_source, occurred_at)
SELECT
  'e-' || z.id || '-' || g.event_type || '-' || to_char(ts, 'YYYYMMDDHH24MI') AS id,
  m.id,
  z.id,
  z.camera_id,
  g.event_type,
  g.detected_object,
  z.name,
  round((0.62 + ((hashval % 33) / 100.0))::numeric, 2),
  g.severity,
  CASE WHEN ts < now() - interval '2 days' THEN 'resolved' ELSE 'new' END,
  'simulated',
  ts
FROM restricted_zones z
JOIN mines m ON m.id = z.mine_id
CROSS JOIN (VALUES
  ('person_without_helmet',      'person', 'high'),
  ('person_without_vest',        'person', 'medium'),
  ('restricted_zone_entry',      'person', 'critical'),
  ('vehicle_in_restricted_area', 'truck',  'high'),
  ('fire_smoke',                 'smoke',  'critical'),
  ('unsafe_crowding',            'group',  'medium')
) AS g(event_type, detected_object, severity)
CROSS JOIN LATERAL (
  SELECT generate_series(
    (now() - interval '9 days')::timestamptz,
    now()::timestamptz,
    interval '11 hours'
  ) AS ts
) series
CROSS JOIN LATERAL (
  SELECT abs(
    get_byte(d, 0)::bigint * 16777216 +
    get_byte(d, 1)::bigint * 65536 +
    get_byte(d, 2)::bigint * 256 +
    get_byte(d, 3)::bigint
  ) AS hashval
  FROM (SELECT decode(substr(md5(m.code || g.event_type || ts::text), 1, 8), 'hex') AS d) h1
) h
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 7) Alerts — environmental (from readings) + safety (from camera events)
--    Both with source traceability so the UI can explain every alert.
-- ----------------------------------------------------------------------------
INSERT INTO alerts (id, mine_id, alert_type, title, description, severity, source, status, source_reading_id, source_event_id, acknowledged_at, resolved_at, created_at)
SELECT
  'a-env-' || r.id                                            AS id,
  r.mine_id,
  'environmental',
  g.rule_name || ' breached at ' || m.name,
  'Simulated reading for ' || r.parameter || ' recorded ' || r.value || ' ' || r.unit ||
    ' (limit ' || r.threshold || ' ' || r.unit || ').',
  g.severity,
  'compliance_engine',
  CASE
    WHEN r.recorded_at < now() - interval '5 days' THEN 'resolved'
    ELSE 'new'
  END,
  r.id,
  NULL,
  CASE WHEN r.recorded_at < now() - interval '5 days'
       THEN r.recorded_at + interval '1 hour' END,
  CASE WHEN r.recorded_at < now() - interval '5 days'
       THEN r.recorded_at + interval '2 hours' END,
  r.recorded_at
FROM environmental_readings r
JOIN mines m ON m.id = r.mine_id
JOIN (VALUES
  ('pm2_5', 'PM2.5 limit', 'high'),
  ('pm10',  'PM10 limit',  'high'),
  ('co',    'CO gas limit','critical')
) AS g(parameter, rule_name, severity) ON g.parameter = r.parameter
WHERE r.status = 'violation'
  AND r.recorded_at >= now() - interval '5 days'
ON CONFLICT (id) DO NOTHING;

INSERT INTO alerts (id, mine_id, alert_type, title, description, severity, source, status, source_event_id, acknowledged_at, resolved_at, created_at)
SELECT
  'a-safety-' || e.id,
  e.mine_id,
  'safety',
  initcap(replace(e.event_type, '_', ' ')) || ' — ' || z.name,
  'Simulated camera ' || e.camera_id || ' flagged ' || replace(e.event_type, '_', ' ') ||
    ' (confidence ' || round(e.confidence::numeric, 2) || ').',
  e.severity,
  'camera_pipeline',
  CASE
    WHEN e.occurred_at < now() - interval '3 days' THEN 'resolved'
    WHEN e.occurred_at < now() - interval '1 day'  THEN 'acknowledged'
    ELSE 'new'
  END,
  e.id,
  CASE WHEN e.occurred_at < now() - interval '3 days' THEN e.occurred_at + interval '30 minutes' END,
  CASE WHEN e.occurred_at < now() - interval '3 days' THEN e.occurred_at + interval '2 hours' END,
  e.occurred_at
FROM camera_events e
JOIN restricted_zones z ON z.id = e.zone_id
WHERE e.severity IN ('high', 'critical')
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 8) Incidents
-- ----------------------------------------------------------------------------
INSERT INTO incidents (id, mine_id, reported_by_id, title, description, category, severity, status, evidence_ref, occurred_at, resolved_at)
VALUES
  ('i-0001', 'm-iron-0001', 'u-safe-0001', 'Minor rockfall at bench 4',
   'Simulated minor rockfall; no injuries; bench cleared and re-inspected.',
   'fall_of_ground', 'medium', 'resolved', 'sim://evidence/rockfall-0001', now() - interval '10 days', now() - interval '8 days'),
  ('i-0002', 'm-coal-0002', 'u-safe-0001', 'CO spike in Gassy Panel 3',
   'Simulated CO concentration spike triggered a gas alert and panel evacuation.',
   'gas', 'critical', 'action_required', 'sim://evidence/co-spike-0002', now() - interval '5 days', NULL),
  ('i-0003', 'm-iron-0001', 'u-mgr-0001', 'Haul truck near-miss with light vehicle',
   'Simulated near-miss on the haul road crossing; dashcam footage referenced.',
   'vehicle', 'high', 'investigating', 'sim://evidence/near-miss-0003', now() - interval '3 days', NULL),
  ('i-0004', 'm-baux-0003', 'u-env-0001', 'Dust exceedance near crusher bay',
   'Simulated PM10 exceedance recorded during crusher maintenance.',
   'other', 'medium', 'open', 'sim://evidence/dust-0004', now() - interval '1 day', NULL)
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 9) Inspections
-- ----------------------------------------------------------------------------
INSERT INTO inspections (id, mine_id, inspector_id, inspection_type, status, scheduled_at, completed_at, compliance_result, findings, notes)
VALUES
  ('ins-0001', 'm-iron-0001', 'u-safe-0001', 'safety',        'completed', now() - interval '7 days', now() - interval '7 days', 'compliant',
   'Simulated finding: PPE compliance strong; signage clear.', 'No corrective action required.'),
  ('ins-0002', 'm-coal-0002', 'u-safe-0001', 'environmental', 'completed', now() - interval '4 days', now() - interval '4 days', 'non_compliant',
   'Simulated finding: ventilation lag in Gassy Panel 3; CO readings trending up.', 'Requires gas-monitoring corrective action.'),
  ('ins-0003', 'm-iron-0001', 'u-mgr-0001',  'equipment',     'in_progress', now() - interval '1 day', NULL, 'pending',
   NULL, 'Simulated haul-road equipment walkdown in progress.'),
  ('ins-0004', 'm-baux-0003', 'u-env-0001',  'compliance',    'scheduled', now() + interval '2 days', NULL, 'pending',
   NULL, 'Simulated compliance walkthrough scheduled post-maintenance.')
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 10) Corrective actions (linked to incidents and inspections)
-- ----------------------------------------------------------------------------
INSERT INTO corrective_actions (id, incident_id, inspection_id, description, assigned_to_id, priority, status, due_date, completion_date, remarks)
VALUES
  ('ca-0001', 'i-0002', NULL,      'Install additional CO sensors in Gassy Panel 3', 'u-mgr-0001', 'critical', 'in_progress', now() + interval '5 days', NULL, 'Simulated procurement in progress.'),
  ('ca-0002', 'i-0003', NULL,      'Deploy speed cameras on haul road crossing',     'u-safe-0001', 'high',    'pending',     now() + interval '10 days', NULL, 'Awaiting vendor quote (simulated).'),
  ('ca-0003', NULL,      'ins-0002','Recalibrate ventilation and re-audit airflow',  'u-env-0001', 'high',     'overdue',     now() - interval '2 days', NULL, 'Overdue — escalated to mine manager.'),
  ('ca-0004', 'i-0001', NULL,      'Reinforce bench-4 slope protection',             'u-mgr-0001', 'medium',   'completed',   now() - interval '9 days', now() - interval '8 days', 'Completed with simulated works order.'),
  ('ca-0005', NULL,      'ins-0002','Update gas emergency drill schedule',            'u-safe-0001', 'medium',   'pending',     now() + interval '14 days', NULL, 'Draft schedule in review.')
ON CONFLICT (id) DO NOTHING;

COMMIT;

-- ============================================================================
-- Summary (optional sanity check after seeding)
-- ============================================================================
-- SELECT 'users' t, count(*) FROM users UNION ALL
-- SELECT 'mines', count(*) FROM mines UNION ALL
-- SELECT 'compliance_rules', count(*) FROM compliance_rules UNION ALL
-- SELECT 'environmental_readings', count(*) FROM environmental_readings UNION ALL
-- SELECT 'restricted_zones', count(*) FROM restricted_zones UNION ALL
-- SELECT 'camera_events', count(*) FROM camera_events UNION ALL
-- SELECT 'alerts', count(*) FROM alerts UNION ALL
-- SELECT 'incidents', count(*) FROM incidents UNION ALL
-- SELECT 'inspections', count(*) FROM inspections UNION ALL
-- SELECT 'corrective_actions', count(*) FROM corrective_actions;
