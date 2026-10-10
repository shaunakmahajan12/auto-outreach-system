"""Full ledger, versioned experience and pgvector. Existing SQLite migrations remain additive."""
from alembic import op
from backend.schema import freeze_baseline
import json
from pathlib import Path
revision='001_engineering'
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    connection=op.get_bind()
    if connection.dialect.name=='postgresql':connection.exec_driver_sql('CREATE EXTENSION IF NOT EXISTS vector')
    if connection.dialect.name!='postgresql':raise RuntimeError('Alembic ledger deployment targets PostgreSQL; local SQLite uses Store.initialize migrations.')
    for statement in json.loads(Path(__file__).with_name('001_schema.json').read_text()):
        # Frozen schema and strict import: only a new deployment is initialized here.
        connection.exec_driver_sql(statement)
    if connection.dialect.name=='postgresql':
        connection.exec_driver_sql('ALTER TABLE experience ADD COLUMN IF NOT EXISTS embedding_vector vector')
        freeze_baseline(connection)

def downgrade():
    raise RuntimeError('Destructive downgrade disabled. Restore the pre-migration backup and previous application version; see docs/operations.md.')
