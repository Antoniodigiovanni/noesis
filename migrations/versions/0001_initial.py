"""Initial Noesis schema."""
from alembic import op

from noesis.persistence.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())
    op.execute("CREATE VIRTUAL TABLE IF NOT EXISTS learning_fts USING fts5(entity_type UNINDEXED, entity_id UNINDEXED, learner_id UNINDEXED, title, body, provenance)")
    op.execute("PRAGMA user_version=1")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS learning_fts")
    Base.metadata.drop_all(op.get_bind())
    op.execute("PRAGMA user_version=0")
