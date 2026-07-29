"""sync_schema_drift — bring existing DB in sync with SQLAlchemy models.

Uses SQLAlchemy inspection for idempotent operations on SQLite and PostgreSQL.
Safe to run on databases where some structures already exist.

Revision ID: 82a73cb4701d
Revises: 99323e08dc27
Create Date: 2026-07-24 17:52:57.219425
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "82a73cb4701d"
down_revision: Union[str, Sequence[str], None] = "99323e08dc27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _index_exists(table: str, name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(idx["name"] == name for idx in sa.inspect(op.get_bind()).get_indexes(table))


def _column_exists(table: str, name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(col["name"] == name for col in sa.inspect(op.get_bind()).get_columns(table))


def _foreign_key_exists(table: str, constrained_column: str, referred_table: str) -> bool:
    if not _table_exists(table):
        return False
    return any(
        constrained_column in (fk.get("constrained_columns") or [])
        and fk.get("referred_table") == referred_table
        for fk in sa.inspect(op.get_bind()).get_foreign_keys(table)
    )


def _foreign_key_named(table: str, name: str) -> bool:
    if not _table_exists(table):
        return False
    return any(fk.get("name") == name for fk in sa.inspect(op.get_bind()).get_foreign_keys(table))


def upgrade() -> None:
    """Apply schema drift fixes with existence guards."""
    # 1. Add index on data_import_batches.id if missing
    if _table_exists("data_import_batches") and not _index_exists("data_import_batches", "ix_data_import_batches_id"):
        with op.batch_alter_table("data_import_batches") as batch_op:
            batch_op.create_index("ix_data_import_batches_id", ["id"], unique=False)

    # 2. Keep notification_configs.wechat_enabled. Runtime notification and
    #    Agent settings code both use it; a later migration adds it where absent.

    # 3. model_preference type: SQLite doesn't support ALTER COLUMN TYPE.
    #    The model defines String(128); existing DB has VARCHAR(64).
    #    SQLite stores both as TEXT — no data loss. Skip.

    # 4. Add FK on work_orders.assignee_id. SQLite PRAGMA foreign_key_list
    #    reports columns but not constraint names. Use table rebuild approach
    #    only if the FK column exists but the FK constraint is missing.
    if (
        _column_exists("work_orders", "assignee_id")
        and _table_exists("users")
        and not _foreign_key_exists("work_orders", "assignee_id", "users")
    ):
            with op.batch_alter_table("work_orders") as batch_op:
                batch_op.create_foreign_key(
                    "fk_wo_assignee_users", "users", ["assignee_id"], ["id"]
                )


def downgrade() -> None:
    """Revert schema drift fixes (best-effort)."""
    # 4. Drop FK if it exists
    if _foreign_key_named("work_orders", "fk_wo_assignee_users"):
        with op.batch_alter_table("work_orders") as batch_op:
            batch_op.drop_constraint("fk_wo_assignee_users", type_="foreignkey")

    # 1. Drop index if exists
    if _index_exists("data_import_batches", "ix_data_import_batches_id"):
        with op.batch_alter_table("data_import_batches") as batch_op:
            batch_op.drop_index("ix_data_import_batches_id")
