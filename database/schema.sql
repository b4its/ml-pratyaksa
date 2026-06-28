-- ==============================================================================
-- PRATYAKSA Database Schema v3.1
-- PostgreSQL 16 + TimescaleDB extension
-- Fixed: AUTOINCREMENT → SERIAL/BIGSERIAL, added unique index on sensor_readings
-- ==============================================================================

-- Enable TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ==============================================================================
-- 1. MASTER DATA
-- ==============================================================================

CREATE TABLE IF NOT EXISTS equipment_units (
    asset_id            VARCHAR(50)  PRIMARY KEY,
    equipment_type      VARCHAR(30)  NOT NULL
        CHECK (equipment_type IN ('haul_truck','excavator','bulldozer','wheel_loader')),
    manufacturer        VARCHAR(50),
    model               VARCHAR(50),
    serial_number       VARCHAR(100),
    commissioned_at     TIMESTAMP,
    nominal_hydraulic_pressure_bar REAL DEFAULT 280.0,
    has_brake_hierarchy BOOLEAN DEFAULT FALSE,
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

-- ==============================================================================
-- 2. SENSOR TIME-SERIES (TimescaleDB hypertable)
-- ==============================================================================

CREATE TABLE IF NOT EXISTS sensor_readings (
    time                    TIMESTAMPTZ     NOT NULL,
    -- CRITICAL FIX: Removed FOREIGN KEY to avoid high-throughput write bottlenecks
    asset_id                VARCHAR(50)     NOT NULL,
    -- Engine telemetry (Converted FLOAT to 32-bit REAL)
    engine_rpm              REAL,
    engine_load_pct         REAL,
    coolant_temp_c          REAL,
    coolant_pressure_kpa    REAL,
    engine_oil_temp_c       REAL,
    engine_oil_pressure_kpa REAL,
    transmission_oil_temp_c REAL,
    transmission_oil_pressure_kpa REAL,
    fuel_consumption_rate_lph REAL,
    boost_pressure_kpa      REAL,
    exhaust_gas_temp_c      REAL,
    battery_voltage_v       REAL,
    -- Physical & fluid
    vibration_x_g           REAL,
    vibration_y_g           REAL,
    vibration_z_g           REAL,
    acoustic_emission_db    REAL,
    hydraulic_main_pump_pressure_bar REAL,
    oil_viscosity_cst       REAL,
    oil_particle_count_iso  REAL,
    oil_moisture_pct        REAL,
    wear_metal_fe_ppm       REAL,
    wear_metal_cu_ppm       REAL,
    -- Environmental context
    payload_tonnage         REAL,
    cycle_time_minutes      REAL,
    haul_distance_km        REAL,
    road_grade_pct          REAL,
    ambient_temp_c          REAL,
    humidity_pct            REAL,
    dust_concentration_mgm3 REAL,
    days_since_last_pm      REAL,
    -- Maintenance logs
    last_maintenance_hours  REAL,
    oil_change_flag         SMALLINT DEFAULT 0,
    -- Quality flags
    connectivity_loss_flag  SMALLINT DEFAULT 0,
    raw_payload_hash        VARCHAR(64)   -- untuk deduplication
);

-- Convert to hypertable
SELECT create_hypertable('sensor_readings', 'time',
                        chunk_time_interval => INTERVAL '7 days',
                        if_not_exists => TRUE);

-- Compress after 30 days
ALTER TABLE sensor_readings SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'asset_id',
    timescaledb.compress_orderby   = 'time DESC'
);
SELECT add_compression_policy('sensor_readings',
    compress_after => INTERVAL '30 days');

-- Retention: drop data older than 2 years
SELECT add_retention_policy('sensor_readings',
    drop_after => INTERVAL '730 days');

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_sensor_asset_time
    ON sensor_readings (asset_id, time DESC);

-- Unique constraint to prevent duplicate readings and enable ON CONFLICT
CREATE UNIQUE INDEX IF NOT EXISTS idx_sensor_unique
    ON sensor_readings (asset_id, time);

-- ==============================================================================
-- 3. PREDICTIONS (TimescaleDB hypertable)
-- ==============================================================================

CREATE TABLE IF NOT EXISTS predictions (
    time                    TIMESTAMPTZ     NOT NULL,
    asset_id                VARCHAR(50)     NOT NULL,
    equipment_type          VARCHAR(30),
    -- XGBoost output
    xgb_anomaly_class       SMALLINT,
    xgb_anomaly_label       VARCHAR(10),
    -- LSTM output (Converted FLOAT to 32-bit REAL)
    lstm_rul_hours          REAL,
    rul_uncertainty         REAL,
    -- Hierarchy RUL
    rul_hydraulic_system    REAL,
    rul_hydraulic_pump      REAL,
    rul_pump_seal_main      REAL,
    rul_brake_system        REAL,
    rul_brake_caliper       REAL,
    rul_brake_pad_rear      REAL,
    rul_steering_system     REAL,
    -- Risk
    risk_level              VARCHAR(10),
    risk_class              SMALLINT,
    model_agreement         BOOLEAN,
    -- Digital twin
    brake_twin_rul          REAL,
    bearing_twin_rul        REAL,
    hydraulic_twin_rul      REAL,
    -- Drift
    drift_detected          BOOLEAN DEFAULT FALSE,
    drift_max_z_score       REAL,
    drift_n_features        INT DEFAULT 0,
    -- Meta
    latency_ms              REAL,
    api_version             VARCHAR(10)
);

SELECT create_hypertable('predictions', 'time',
                          chunk_time_interval => INTERVAL '7 days',
                          if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_predictions_asset_time
    ON predictions (asset_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_risk
    ON predictions (risk_class, time DESC)
    WHERE risk_class >= 1;

-- Continuous aggregate: hourly summary per unit
CREATE MATERIALIZED VIEW IF NOT EXISTS predictions_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    asset_id,
    equipment_type,
    AVG(lstm_rul_hours)       AS avg_rul_hours,
    MIN(lstm_rul_hours)       AS min_rul_hours,
    AVG(rul_uncertainty)      AS avg_uncertainty,
    MAX(risk_class)           AS max_risk_class,
    COUNT(*)                  AS n_readings,
    SUM(CASE WHEN drift_detected THEN 1 ELSE 0 END) AS n_drift_events
FROM predictions
GROUP BY bucket, asset_id, equipment_type
WITH NO DATA;

SELECT add_continuous_aggregate_policy('predictions_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');

-- ==============================================================================
-- 4. ALERTS & WORK ORDERS
-- ==============================================================================

CREATE TABLE IF NOT EXISTS alerts (
    id              BIGSERIAL       PRIMARY KEY,
    asset_id        VARCHAR(50)     NOT NULL,
    created_at      TIMESTAMPTZ     DEFAULT NOW(),
    risk_level      VARCHAR(10)     NOT NULL,
    rul_hours       REAL,
    component       VARCHAR(100),
    message         TEXT,
    shap_top3       JSONB,          -- top 3 SHAP contributors
    acknowledged    BOOLEAN DEFAULT FALSE,
    acknowledged_by VARCHAR(100),
    acknowledged_at TIMESTAMPTZ,
    work_order_id   VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_alerts_asset_created
    ON alerts (asset_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_unacked
    ON alerts (acknowledged, risk_level)
    WHERE acknowledged = FALSE;

CREATE TABLE IF NOT EXISTS work_orders (
    id                  VARCHAR(50)     PRIMARY KEY,  -- dari CMMS
    asset_id            VARCHAR(50)     NOT NULL,
    alert_id            BIGINT          REFERENCES alerts(id),
    created_at          TIMESTAMPTZ     DEFAULT NOW(),
    scheduled_at        TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    status              VARCHAR(20)     DEFAULT 'OPEN'
        CHECK (status IN ('OPEN','IN_PROGRESS','COMPLETED','CANCELLED')),
    component           VARCHAR(100),
    part_number         VARCHAR(100),
    -- Best practice: currency stored as NUMERIC
    estimated_cost_usd  NUMERIC(12,2),
    actual_cost_usd     NUMERIC(12,2),
    technician          VARCHAR(100),
    notes               TEXT,
    -- Feedback untuk continual learning
    actual_condition    VARCHAR(50),    -- 'as_predicted', 'worse', 'better', 'false_alarm'
    feedback_logged     BOOLEAN DEFAULT FALSE
);

-- ==============================================================================
-- 5. MODEL REGISTRY (MLflow backend — dikelola MLflow, tabel ini sebagai mirror)
-- ==============================================================================

CREATE TABLE IF NOT EXISTS model_deployments (
    id              BIGSERIAL       PRIMARY KEY,
    model_type      VARCHAR(20)     NOT NULL CHECK (model_type IN ('xgb','lstm')),
    equipment_type  VARCHAR(30),
    model_version   VARCHAR(20),
    mlflow_run_id   VARCHAR(50),
    deployed_at     TIMESTAMPTZ     DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE,
    mae_critical    REAL,
    mae_warning     REAL,
    bias_critical   REAL,
    gate_pass       BOOLEAN,
    notes           TEXT
);

-- ==============================================================================
-- 6. DRIFT LOG
-- ==============================================================================

CREATE TABLE IF NOT EXISTS drift_log (
    id              BIGSERIAL       PRIMARY KEY,
    logged_at       TIMESTAMPTZ     DEFAULT NOW(),
    asset_id        VARCHAR(50),
    equipment_type  VARCHAR(30),
    drifted_features JSONB,
    max_z_score     REAL,
    n_drifted       INT,
    retraining_triggered BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_drift_logged
    ON drift_log (logged_at DESC, equipment_type);

-- ==============================================================================
-- 7. UTILITY VIEWS
-- ==============================================================================

-- Fleet health snapshot (dashboard utama)
CREATE OR REPLACE VIEW v_fleet_health AS
SELECT
    e.asset_id,
    e.equipment_type,
    e.manufacturer,
    e.model,
    p.risk_level,
    p.risk_class,
    p.lstm_rul_hours,
    p.rul_uncertainty,
    p.rul_hydraulic_pump,
    p.rul_brake_pad_rear,
    p.drift_detected,
    p.time AS last_prediction_at,
    p.model_agreement,
    CASE
        WHEN p.time < NOW() - INTERVAL '10 minutes' THEN TRUE
        ELSE FALSE
    END AS is_stale
FROM equipment_units e
LEFT JOIN LATERAL (
    SELECT * FROM predictions
    WHERE asset_id = e.asset_id
    ORDER BY time DESC
    LIMIT 1
) p ON TRUE
WHERE e.is_active = TRUE;

-- Active alerts per unit
CREATE OR REPLACE VIEW v_active_alerts AS
SELECT
    a.asset_id,
    a.risk_level,
    a.rul_hours,
    a.component,
    a.message,
    a.created_at,
    a.shap_top3,
    a.work_order_id
FROM alerts a
WHERE a.acknowledged = FALSE
ORDER BY
    CASE a.risk_level WHEN 'CRITICAL' THEN 0 WHEN 'WARNING' THEN 1 ELSE 2 END,
    a.created_at DESC;

-- ==============================================================================
-- 8. SPARE PARTS INVENTORY (Prescriptive Engine)
-- ==============================================================================

CREATE TABLE IF NOT EXISTS spare_parts (
    id SERIAL PRIMARY KEY,
    component TEXT NOT NULL,
    part_number TEXT NOT NULL,
    name TEXT NOT NULL,
    cost REAL NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0,
    reorder_level INTEGER DEFAULT 5
);