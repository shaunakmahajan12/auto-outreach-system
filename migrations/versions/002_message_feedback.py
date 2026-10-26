"""Independent message feedback; additive, preserving legacy observations."""

from alembic import op

revision = '002_feedback'
down_revision = '001_engineering'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        'CREATE TABLE IF NOT EXISTS message_feedback(suggestion_id TEXT NOT NULL REFERENCES draft_suggestions(id), kind TEXT NOT NULL, accepted INTEGER NOT NULL, edited INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(suggestion_id,kind))'
    )


def downgrade():
    raise RuntimeError(
        'Restore the pre-migration backup and previous application version; feedback history is preserved.'
    )
