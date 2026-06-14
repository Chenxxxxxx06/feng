"""Automated migration from SQLite to PostgreSQL.

Migrates all 12 tables from the local SQLite fengdiao_phm.db to a PostgreSQL
fengdiao_phm database. Handles type conversion, JSON columns, foreign keys,
and batch processing for the large SCADA table (>5M rows).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("psycopg2 not found. Run: pip install psycopg2-binary")
    sys.exit(1)


SQLITE_DB = "database/fengdiao_phm.db"

PG_PARAMS = {
    "host": "localhost",
    "port": 5432,
    "dbname": "fengdiao_phm",
    "user": "postgres",
    "password": "",
}

BATCH_SIZE = 50000

TABLES_IN_ORDER = [
    "users",
    "turbines",
    "data_sources",
    "data_import_batches",
    "faults",
    "fault_signals",
    "rul_predictions",
    "scada_records",
    "work_orders",
    "vibration_data",
    "blade_images",
    "notification_configs",
]

QUICK_TABLES = [
    "users",
    "turbines",
    "data_sources",
    "data_import_batches",
    "faults",
    "fault_signals",
    "rul_predictions",
    "work_orders",
    "notification_configs",
]

DROP_TABLE_ORDER = list(reversed(TABLES_IN_ORDER))

PG_CREATE_SQL = {
    "turbines": """
        CREATE TABLE turbines (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(64) NOT NULL,
            model VARCHAR(64),
            power_mw FLOAT,
            lat FLOAT,
            lng FLOAT,
            region VARCHAR(32),
            status VARCHAR(16),
            hi_value FLOAT,
            last_maintenance TIMESTAMP,
            commissioned_at TIMESTAMP,
            source_dataset VARCHAR(64),
            source_asset_id VARCHAR(128),
            asset_scope VARCHAR(32),
            geo_scope VARCHAR(32),
            CONSTRAINT uq_turbine_source_asset UNIQUE (source_dataset, source_asset_id)
        )
    """,
    "scada_records": """
        CREATE TABLE scada_records (
            id INTEGER NOT NULL PRIMARY KEY,
            turbine_id INTEGER NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            power_kw FLOAT,
            wind_speed_ms FLOAT,
            rotor_rpm FLOAT,
            gen_temperature_c FLOAT,
            gearbox_temperature_c FLOAT,
            bearing_temperature_c FLOAT,
            pitch_angle_deg FLOAT,
            nacelle_direction_deg FLOAT,
            grid_frequency_hz FLOAT,
            ambient_temp_c FLOAT,
            extra JSONB
        )
    """,
    "data_sources": """
        CREATE TABLE data_sources (
            id INTEGER NOT NULL PRIMARY KEY,
            source_type VARCHAR(32) NOT NULL,
            name VARCHAR(64) NOT NULL,
            connection_params JSONB,
            status VARCHAR(16),
            last_connected_at TIMESTAMP,
            last_data_at TIMESTAMP
        )
    """,
    "data_import_batches": """
        CREATE TABLE data_import_batches (
            id SERIAL PRIMARY KEY,
            dataset_id VARCHAR(64) NOT NULL,
            source_type VARCHAR(32) NOT NULL,
            status VARCHAR(16) NOT NULL,
            started_at TIMESTAMP NOT NULL,
            completed_at TIMESTAMP,
            manifest_path TEXT,
            field_mapping_version TEXT,
            files_total INTEGER,
            files_imported INTEGER,
            rows_imported INTEGER,
            rows_skipped INTEGER,
            anonymous_assets INTEGER,
            summary JSONB
        )
    """,
    "vibration_data": """
        CREATE TABLE vibration_data (
            id INTEGER NOT NULL PRIMARY KEY,
            turbine_id INTEGER NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            component VARCHAR(32) NOT NULL,
            rms FLOAT,
            peak_freq_hz FLOAT,
            waveform_path VARCHAR(256)
        )
    """,
    "blade_images": """
        CREATE TABLE blade_images (
            id INTEGER NOT NULL PRIMARY KEY,
            turbine_id INTEGER NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            image_path VARCHAR(256) NOT NULL,
            diagnosis_type VARCHAR(32),
            diagnosis_confidence FLOAT,
            damage_bbox JSONB
        )
    """,
    "faults": """
        CREATE TABLE faults (
            id INTEGER NOT NULL PRIMARY KEY,
            turbine_id INTEGER NOT NULL,
            detected_at TIMESTAMP,
            fault_type VARCHAR(64) NOT NULL,
            confidence FLOAT NOT NULL,
            status VARCHAR(16),
            details JSONB
        )
    """,
    "rul_predictions": """
        CREATE TABLE rul_predictions (
            id INTEGER NOT NULL PRIMARY KEY,
            turbine_id INTEGER NOT NULL,
            component VARCHAR(32) NOT NULL,
            predicted_at TIMESTAMP,
            remaining_life_days FLOAT NOT NULL,
            confidence_lower FLOAT NOT NULL,
            confidence_upper FLOAT NOT NULL
        )
    """,
    "notification_configs": """
        CREATE TABLE notification_configs (
            id INTEGER NOT NULL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            hi_threshold FLOAT,
            email_enabled BOOLEAN,
            email_address VARCHAR(128),
            wechat_enabled BOOLEAN,
            created_at TIMESTAMP
        )
    """,
    "fault_signals": """
        CREATE TABLE fault_signals (
            id INTEGER NOT NULL PRIMARY KEY,
            fault_id INTEGER NOT NULL,
            sensor_name VARCHAR(64) NOT NULL,
            contribution_score FLOAT NOT NULL,
            priority VARCHAR(8)
        )
    """,
    "work_orders": """
        CREATE TABLE work_orders (
            id INTEGER NOT NULL PRIMARY KEY,
            turbine_id INTEGER NOT NULL,
            fault_id INTEGER,
            title VARCHAR(128) NOT NULL,
            description TEXT,
            status VARCHAR(16),
            assignee VARCHAR(64),
            cost_estimate FLOAT,
            cost_actual FLOAT,
            created_at TIMESTAMP,
            completed_at TIMESTAMP,
            downtime_hours FLOAT
        )
    """,
    "users": """
        CREATE TABLE users (
            id INTEGER NOT NULL PRIMARY KEY,
            username VARCHAR(64) NOT NULL UNIQUE,
            email VARCHAR(128) NOT NULL UNIQUE,
            password_hash VARCHAR(256) NOT NULL,
            role VARCHAR(32),
            api_key VARCHAR(256),
            model_preference VARCHAR(64),
            is_active BOOLEAN,
            created_at TIMESTAMP
        )
    """,
}

PG_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_turbines_name ON turbines (name);",
    "CREATE INDEX IF NOT EXISTS ix_turbines_source_dataset ON turbines (source_dataset);",
    "CREATE INDEX IF NOT EXISTS ix_turbines_source_asset_id ON turbines (source_asset_id);",
    "CREATE INDEX IF NOT EXISTS ix_scada_records_turbine_id ON scada_records (turbine_id);",
    "CREATE INDEX IF NOT EXISTS ix_scada_records_timestamp ON scada_records (timestamp);",
    "CREATE INDEX IF NOT EXISTS ix_data_import_batches_dataset_id ON data_import_batches (dataset_id);",
    "CREATE INDEX IF NOT EXISTS ix_vibration_data_turbine_id ON vibration_data (turbine_id);",
    "CREATE INDEX IF NOT EXISTS ix_vibration_data_timestamp ON vibration_data (timestamp);",
    "CREATE INDEX IF NOT EXISTS ix_blade_images_turbine_id ON blade_images (turbine_id);",
    "CREATE INDEX IF NOT EXISTS ix_faults_turbine_id ON faults (turbine_id);",
    "CREATE INDEX IF NOT EXISTS ix_fault_signals_fault_id ON fault_signals (fault_id);",
    "CREATE INDEX IF NOT EXISTS ix_rul_predictions_turbine_id ON rul_predictions (turbine_id);",
    "CREATE INDEX IF NOT EXISTS ix_work_orders_turbine_id ON work_orders (turbine_id);",
    "CREATE INDEX IF NOT EXISTS ix_notification_configs_user_id ON notification_configs (user_id);",
]

JSON_COLUMNS = {
    "data_import_batches": ["summary"],
    "data_sources": ["connection_params"],
    "scada_records": ["extra"],
    "faults": ["details"],
    "blade_images": ["damage_bbox"],
}

BOOLEAN_COLUMNS = {
    "users": ["is_active"],
    "notification_configs": ["email_enabled", "wechat_enabled"],
}

AUTOINCREMENT_TABLES = {"data_import_batches"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_sqlite(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def connect_postgres(params: dict) -> psycopg2.extensions.connection:
    conn = psycopg2.connect(**params)
    conn.autocommit = False
    return conn


def drop_all_tables(pg_cur) -> None:
    pg_cur.execute("SET session_replication_role = 'replica';")
    for table in DROP_TABLE_ORDER:
        pg_cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
    pg_cur.execute("SET session_replication_role = 'origin';")
    pg_cur.connection.commit()
    print("  已删除所有旧表")


def create_all_tables(pg_cur) -> None:
    for table in TABLES_IN_ORDER:
        if table in PG_CREATE_SQL:
            pg_cur.execute(PG_CREATE_SQL[table])
        else:
            print(f"  警告: 表 {table} 没有建表SQL，跳过")
    pg_cur.connection.commit()
    print("  12张表已重新创建")


def create_indexes(pg_cur) -> None:
    for sql in PG_INDEX_SQL:
        pg_cur.execute(sql)
    pg_cur.connection.commit()
    print("  索引已创建")


def migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn: psycopg2.extensions.connection,
    table: str,
) -> int:
    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()

    is_autoincrement = table in AUTOINCREMENT_TABLES
    json_cols = JSON_COLUMNS.get(table, [])
    bool_cols = BOOLEAN_COLUMNS.get(table, [])

    sqlite_cur.execute(f"SELECT * FROM {table}")
    rows = sqlite_cur.fetchall()
    if not rows:
        print(f"  [{table}] 0 条记录（空表），跳过")
        return 0

    column_names = [desc[0] for desc in sqlite_cur.description]
    insert_cols = column_names if not is_autoincrement else [c for c in column_names if c != "id"]

    placeholders = ", ".join(["%s"] * len(insert_cols))
    col_list = ", ".join(insert_cols)
    insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"

    total = len(rows)

    if total <= BATCH_SIZE:
        prepared_rows = _prepare_rows(rows, column_names, insert_cols, json_cols, bool_cols)
        psycopg2.extras.execute_batch(pg_cur, insert_sql, prepared_rows, page_size=5000)
        pg_conn.commit()

        if is_autoincrement:
            _reset_serial(pg_cur, table)

        print(f"  [{table}] {total} 条记录 完成")
        return total

    batch_count = 0
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        prepared_rows = _prepare_rows(batch, column_names, insert_cols, json_cols, bool_cols)
        psycopg2.extras.execute_batch(pg_cur, insert_sql, prepared_rows, page_size=5000)
        pg_conn.commit()
        batch_count += len(batch)
        pct = batch_count * 100 // total
        print(f"  [{table}] {batch_count}/{total} ({pct}%) ...", flush=True)

    if is_autoincrement:
        _reset_serial(pg_cur, table)

    print(f"  [{table}] {total} 条记录 完成")
    return total


def _prepare_rows(rows, column_names, insert_cols, json_cols, bool_cols):
    prepared = []
    for row in rows:
        row_dict = dict(row) if isinstance(row, sqlite3.Row) else dict(zip(column_names, row))
        values = []
        for col in insert_cols:
            val = row_dict.get(col)
            if col in bool_cols and val is not None:
                values.append(bool(val))
            elif col in json_cols and val is not None:
                values.append(json.dumps(json.loads(val)) if isinstance(val, str) else json.dumps(val))
            else:
                values.append(val)
        prepared.append(tuple(values))
    return prepared


def _reset_serial(pg_cur, table: str) -> None:
    """设置 PostgreSQL SERIAL 序列的起始值"""
    pg_cur.execute(
        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
        f"COALESCE((SELECT MAX(id) FROM {table}), 0));"
    )


def add_foreign_keys(pg_cur) -> None:
    fk_sql = [
        "ALTER TABLE scada_records ADD CONSTRAINT fk_scada_turbine FOREIGN KEY (turbine_id) REFERENCES turbines(id);",
        "ALTER TABLE vibration_data ADD CONSTRAINT fk_vibration_turbine FOREIGN KEY (turbine_id) REFERENCES turbines(id);",
        "ALTER TABLE blade_images ADD CONSTRAINT fk_blade_turbine FOREIGN KEY (turbine_id) REFERENCES turbines(id);",
        "ALTER TABLE faults ADD CONSTRAINT fk_faults_turbine FOREIGN KEY (turbine_id) REFERENCES turbines(id);",
        "ALTER TABLE fault_signals ADD CONSTRAINT fk_signals_fault FOREIGN KEY (fault_id) REFERENCES faults(id);",
        "ALTER TABLE rul_predictions ADD CONSTRAINT fk_rul_turbine FOREIGN KEY (turbine_id) REFERENCES turbines(id);",
        "ALTER TABLE work_orders ADD CONSTRAINT fk_wo_turbine FOREIGN KEY (turbine_id) REFERENCES turbines(id);",
        "ALTER TABLE work_orders ADD CONSTRAINT fk_wo_fault FOREIGN KEY (fault_id) REFERENCES faults(id);",
        "ALTER TABLE notification_configs ADD CONSTRAINT fk_notif_user FOREIGN KEY (user_id) REFERENCES users(id);",
    ]
    for sql in fk_sql:
        try:
            pg_cur.execute(sql)
        except Exception as e:
            print(f"  外键跳过: {str(e)[:80]}")
    pg_cur.connection.commit()
    print("  外键约束已添加")


def verify_migration(pg_conn) -> bool:
    cur = pg_conn.cursor()
    cur.execute("""
        SELECT
            'blade_images'::text AS t, COUNT(*) FROM blade_images
        UNION ALL SELECT 'data_import_batches', COUNT(*) FROM data_import_batches
        UNION ALL SELECT 'data_sources', COUNT(*) FROM data_sources
        UNION ALL SELECT 'fault_signals', COUNT(*) FROM fault_signals
        UNION ALL SELECT 'faults', COUNT(*) FROM faults
        UNION ALL SELECT 'notification_configs', COUNT(*) FROM notification_configs
        UNION ALL SELECT 'rul_predictions', COUNT(*) FROM rul_predictions
        UNION ALL SELECT 'scada_records', COUNT(*) FROM scada_records
        UNION ALL SELECT 'turbines', COUNT(*) FROM turbines
        UNION ALL SELECT 'users', COUNT(*) FROM users
        UNION ALL SELECT 'vibration_data', COUNT(*) FROM vibration_data
        UNION ALL SELECT 'work_orders', COUNT(*) FROM work_orders
        ORDER BY t;
    """)
    rows = cur.fetchall()

    expected = {
        "blade_images": 0,
        "data_import_batches": 2,
        "data_sources": 5,
        "fault_signals": 40,
        "faults": 8,
        "notification_configs": 1,
        "rul_predictions": 93,
        "scada_records": 5247268,
        "turbines": 66,
        "users": 5,
        "vibration_data": 0,
        "work_orders": 8,
    }

    all_ok = True
    print("\n" + "=" * 55)
    print("  验证迁移结果")
    print("=" * 55)
    print(f"  {'表名':<25} {'实际':>8} {'预期':>8} {'状态'}")
    print("  " + "-" * 53)
    for t, count in rows:
        exp = expected.get(t, "?")
        status = "OK" if count == exp else "MISMATCH"
        if count != exp:
            all_ok = False
        print(f"  {t:<25} {count:>8} {str(exp):>8} {status}")
    print("=" * 55)

    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite fengdiao_phm to PostgreSQL")
    parser.add_argument("--db-path", default="database/fengdiao_phm.db", help="SQLite database path")
    parser.add_argument("--pg-host", default="localhost")
    parser.add_argument("--pg-port", default=5432, type=int)
    parser.add_argument("--pg-dbname", default="fengdiao_phm")
    parser.add_argument("--pg-user", default="postgres")
    parser.add_argument("--pg-password", default="")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Check connections only, do not migrate")
    parser.add_argument("--quick", action="store_true", help="快速模式：跳过 scada_records 等大表，只同步业务表（秒级完成）")
    args = parser.parse_args()

    pg_params = {
        "host": args.pg_host,
        "port": args.pg_port,
        "dbname": args.pg_dbname,
        "user": args.pg_user,
        "password": args.pg_password,
    }

    print(f"[{now_iso()}] 开始 SQLite → PostgreSQL 迁移")
    print(f"  SQLite: {args.db_path}")
    print(f"  PostgreSQL: {args.pg_host}:{args.pg_port}/{args.pg_dbname} (user={args.pg_user})")

    if args.dry_run:
        try:
            conn = connect_sqlite(args.db_path)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM scada_records")
            print(f"  SQLite 连接成功, scada_records={cur.fetchone()[0]} 条")
            conn.close()

            conn = connect_postgres(pg_params)
            cur = conn.cursor()
            cur.execute("SELECT version();")
            print(f"  PostgreSQL 连接成功, {cur.fetchone()[0][:50]}...")
            conn.close()
            print("  --dry-run 验证通过，可以开始迁移")
            return
        except Exception as e:
            print(f"  连接失败: {e}")
            sys.exit(1)

    sqlite_conn = connect_sqlite(args.db_path)
    pg_conn = connect_postgres(pg_params)
    pg_cur = pg_conn.cursor()

    if args.quick:
        print("\n  [快速模式] 仅同步业务小表，跳过 scada_records / vibration_data / blade_images")
        tables_to_migrate = QUICK_TABLES
        drop_order = list(reversed(QUICK_TABLES))

        print("\n[1/3] 清理业务表...")
        pg_cur.execute("SET session_replication_role = 'replica';")
        for table in drop_order:
            pg_cur.execute(f"DELETE FROM {table};")
        pg_cur.execute("SET session_replication_role = 'origin';")
        pg_cur.connection.commit()

        print("\n[2/3] 同步业务数据...")
        grand_total = 0
        for table in tables_to_migrate:
            count = migrate_table(sqlite_conn, pg_conn, table)
            grand_total += count

        print(f"\n  总计同步 {grand_total} 条记录（秒级完成）")
    else:
        tables_to_migrate = TABLES_IN_ORDER

        print("\n[1/4] 清理旧表...")
        drop_all_tables(pg_cur)

        print("\n[2/4] 创建新表...")
        create_all_tables(pg_cur)

        print("\n[3/4] 迁移数据...")
        grand_total = 0
        for table in tables_to_migrate:
            count = migrate_table(sqlite_conn, pg_conn, table)
            grand_total += count

        print(f"\n  总计迁移 {grand_total} 条记录")

        print("\n[4/4] 添加索引和外键...")
        create_indexes(pg_cur)
        add_foreign_keys(pg_cur)

    sqlite_conn.close()

    if not args.skip_verify:
        ok = verify_migration(pg_conn)

    pg_conn.close()

    if not args.skip_verify and ok:
        print("\n  迁移成功！")
    elif not args.skip_verify:
        print("\n  迁移完成，但部分记录数不匹配，请检查。")
    else:
        print("\n  迁移完成（跳过验证）。")


if __name__ == "__main__":
    main()