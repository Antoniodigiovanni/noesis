"""Accounts, decks, immutable card revisions and self-graded review evidence."""
from alembic import op
from noesis.persistence.models import Base
import noesis.persistence.web_models
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(op.get_bind(), tables=[t for t in Base.metadata.sorted_tables if t.name.startswith('app_')])


def downgrade():
    raise RuntimeError('Destructive downgrade unsupported. Restore a verified pre-upgrade backup into a separate database.')
