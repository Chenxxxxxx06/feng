"""Add active domain tables, schema links, and the SCADA access-path index.

The application historically relied on ``Base.metadata.create_all`` for the
inventory, supply-chain, quality and production tables. This migration makes
that incremental schema explicit while remaining safe for databases where
``create_all`` has already created some or all of the tables.

Revision ID: c4d9f2a1e6b8
Revises: 82a73cb4701d
Create Date: 2026-07-28 23:20:00 +09:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.database import Base
from app import models as _models  # noqa: F401 - register all tables in metadata


revision: str = "c4d9f2a1e6b8"
down_revision: Union[str, Sequence[str], None] = "82a73cb4701d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ACTIVE_DOMAIN_TABLES = (
    "power_forecasts",
    "production_plans",
    "resource_locks",
    "resource_bids",
)
SCADA_INDEX = "ix_scada_turbine_timestamp"
WORKORDER_INCIDENT_INDEX = "ix_work_orders_incident_id"


def _table_exists(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _index_exists(table: str, name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(index["name"] == name for index in sa.inspect(op.get_bind()).get_indexes(table))


def _column_exists(table: str, name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(column["name"] == name for column in sa.inspect(op.get_bind()).get_columns(table))


def _foreign_key_exists(table: str, constrained_column: str, referred_table: str) -> bool:
    if not _table_exists(table):
        return False
    return any(
        constrained_column in (fk.get("constrained_columns") or [])
        and fk.get("referred_table") == referred_table
        for fk in sa.inspect(op.get_bind()).get_foreign_keys(table)
    )


def upgrade() -> None:
    """Create only missing domain tables, then add the SCADA query index."""
    bind = op.get_bind()
    for table_name in ACTIVE_DOMAIN_TABLES:
        if not _table_exists(table_name):
            table = Base.metadata.tables.get(table_name)
            if table is None:
                raise RuntimeError(f"Active model table is not registered: {table_name}")
            table.create(bind=bind, checkfirst=True)

    if _table_exists("notification_configs") and not _column_exists(
        "notification_configs", "wechat_enabled"
    ):
        with op.batch_alter_table("notification_configs") as batch_op:
            batch_op.add_column(
                sa.Column("wechat_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
            )

    if _table_exists("work_orders") and not _column_exists("work_orders", "incident_id"):
        with op.batch_alter_table("work_orders") as batch_op:
            batch_op.add_column(sa.Column("incident_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_work_orders_incident_id",
                "incidents",
                ["incident_id"],
                ["id"],
            )

    if (
        _table_exists("work_orders")
        and _column_exists("work_orders", "incident_id")
        and not _foreign_key_exists("work_orders", "incident_id", "incidents")
    ):
        with op.batch_alter_table("work_orders") as batch_op:
            batch_op.create_foreign_key(
                "fk_work_orders_incident_id",
                "incidents",
                ["incident_id"],
                ["id"],
            )

    if _table_exists("work_orders") and not _index_exists("work_orders", WORKORDER_INCIDENT_INDEX):
        op.create_index(
            WORKORDER_INCIDENT_INDEX,
            "work_orders",
            ["incident_id"],
            unique=False,
        )

    if _table_exists("scada_records") and not _index_exists("scada_records", SCADA_INDEX):
        op.create_index(
            SCADA_INDEX,
            "scada_records",
            ["turbine_id", "timestamp"],
            unique=False,
        )


def downgrade() -> None:
    """Remove the additive index but preserve domain tables and their data."""
    if _index_exists("scada_records", SCADA_INDEX):
        op.drop_index(SCADA_INDEX, table_name="scada_records")
