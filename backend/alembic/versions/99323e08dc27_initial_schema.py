"""initial_schema — baseline revision anchor.

All tables already exist in the database (created by Base.metadata.create_all
in main.py). This revision serves as the Alembic version anchor so future
autogenerate migrations can detect schema drift incrementally.

For existing databases: `alembic stamp head`
For empty databases: run the application once (creates tables via create_all),
  then `alembic stamp head`

Revision ID: 99323e08dc27
Revises:
Create Date: 2026-07-24 17:51:48.807709
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "99323e08dc27"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op: tables already exist in the database."""
    pass


def downgrade() -> None:
    """No-op: baseline cannot be downgraded."""
    pass
