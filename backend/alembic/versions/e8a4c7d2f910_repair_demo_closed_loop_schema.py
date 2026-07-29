"""Repair closed-loop columns for databases stamped before the schema update.

Some existing SQLite databases were already stamped at ``c4d9f2a1e6b8`` before
the work-order incident link and notification channel column were added to that
revision.  A new revision is required because editing an already-applied
migration cannot update those databases.

Revision ID: e8a4c7d2f910
Revises: c4d9f2a1e6b8
Create Date: 2026-07-29 14:20:00 +08:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8a4c7d2f910"
down_revision: Union[str, Sequence[str], None] = "c4d9f2a1e6b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


WORKORDER_INCIDENT_INDEX = "ix_work_orders_incident_id"


def _table_exists(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _column_exists(table: str, name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(column["name"] == name for column in sa.inspect(op.get_bind()).get_columns(table))


def _index_exists(table: str, name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(index["name"] == name for index in sa.inspect(op.get_bind()).get_indexes(table))


def _foreign_key_exists(table: str, constrained_column: str, referred_table: str) -> bool:
    if not _table_exists(table):
        return False
    return any(
        constrained_column in (fk.get("constrained_columns") or [])
        and fk.get("referred_table") == referred_table
        for fk in sa.inspect(op.get_bind()).get_foreign_keys(table)
    )


def upgrade() -> None:
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

    if (
        _table_exists("work_orders")
        and _column_exists("work_orders", "incident_id")
        and not _index_exists("work_orders", WORKORDER_INCIDENT_INDEX)
    ):
        op.create_index(
            WORKORDER_INCIDENT_INDEX,
            "work_orders",
            ["incident_id"],
            unique=False,
        )


def downgrade() -> None:
    # Keep the additive compatibility columns. Removing them would break data
    # written by the closed-loop workflow and is intentionally not automatic.
    pass
