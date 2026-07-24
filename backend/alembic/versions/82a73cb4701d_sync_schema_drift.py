"""sync_schema_drift — bring existing DB in sync with SQLAlchemy models.

Uses PRAGMA-based existence checks for idempotent operations on SQLite.
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


def _pragma_index_list(table: str) -> list[dict]:
    """Return list of indexes on table via PRAGMA."""
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"PRAGMA index_list('{table}')")).fetchall()
    return [{"name": row[1], "unique": bool(row[2])} for row in rows]


def _pragma_table_info(table: str) -> list[dict]:
    """Return list of columns in table via PRAGMA."""
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"PRAGMA table_info('{table}')")).fetchall()
    return [{"name": row[1], "type": row[2]} for row in rows]


def _index_exists(table: str, name: str) -> bool:
    return any(idx["name"] == name for idx in _pragma_index_list(table))


def _column_exists(table: str, name: str) -> bool:
    return any(col["name"] == name for col in _pragma_table_info(table))


def upgrade() -> None:
    """Apply schema drift fixes with existence guards."""
    # 1. Add index on data_import_batches.id if missing
    if not _index_exists("data_import_batches", "ix_data_import_batches_id"):
        with op.batch_alter_table("data_import_batches") as batch_op:
            batch_op.create_index("ix_data_import_batches_id", ["id"], unique=False)

    # 2. Drop orphaned wechat_enabled column if present
    if _column_exists("notification_configs", "wechat_enabled"):
        with op.batch_alter_table("notification_configs") as batch_op:
            batch_op.drop_column("wechat_enabled")

    # 3. model_preference type: SQLite doesn't support ALTER COLUMN TYPE.
    #    The model defines String(128); existing DB has VARCHAR(64).
    #    SQLite stores both as TEXT — no data loss. Skip.

    # 4. Add FK on work_orders.assignee_id. SQLite PRAGMA foreign_key_list
    #    reports columns but not constraint names. Use table rebuild approach
    #    only if the FK column exists but the FK constraint is missing.
    if _column_exists("work_orders", "assignee_id"):
        fk_list = op.get_bind().execute(
            sa.text("PRAGMA foreign_key_list('work_orders')")
        ).fetchall()
        has_fk = any(row[3] == "assignee_id" and row[2] == "users" for row in fk_list)
        if not has_fk:
            with op.batch_alter_table("work_orders") as batch_op:
                batch_op.create_foreign_key(
                    "fk_wo_assignee_users", "users", ["assignee_id"], ["id"]
                )


def downgrade() -> None:
    """Revert schema drift fixes (best-effort)."""
    # 4. Drop FK if it exists
    fk_list = op.get_bind().execute(
        sa.text("PRAGMA foreign_key_list('work_orders')")
    ).fetchall()
    has_fk = any(row[3] == "assignee_id" and row[2] == "users" for row in fk_list)
    if has_fk:
        with op.batch_alter_table("work_orders") as batch_op:
            batch_op.drop_constraint("fk_wo_assignee_users", type_="foreignkey")

    # 2. Re-add wechat_enabled if missing
    if not _column_exists("notification_configs", "wechat_enabled"):
        with op.batch_alter_table("notification_configs") as batch_op:
            batch_op.add_column(
                sa.Column("wechat_enabled", sa.Boolean(), nullable=True)
            )

    # 1. Drop index if exists
    if _index_exists("data_import_batches", "ix_data_import_batches_id"):
        with op.batch_alter_table("data_import_batches") as batch_op:
            batch_op.drop_index("ix_data_import_batches_id")
