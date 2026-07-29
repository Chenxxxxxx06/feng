"""initial_schema — idempotent baseline revision.

Existing deployments historically created tables through
``Base.metadata.create_all`` before Alembic was introduced. Keep that behavior
for compatibility, but also create missing tables here so a clean database can
be upgraded from zero without requiring an application startup first.

Revision ID: 99323e08dc27
Revises:
Create Date: 2026-07-24 17:51:48.807709
"""
from typing import Sequence, Union

from alembic import op

from app.database import Base
from app import models as _models  # noqa: F401 - register all tables in metadata

# revision identifiers
revision: str = "99323e08dc27"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the baseline schema without changing tables that already exist."""
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    """No-op: baseline cannot be downgraded."""
    pass
