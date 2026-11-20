"""Explicit one-shot transfer from a quiesced SQLite backup. Never mutates source."""
from pathlib import Path
from urllib.parse import quote
from sqlalchemy import DateTime
from noesis.application.common import as_utc
from sqlalchemy import create_engine, select, inspect
from noesis.persistence.models import Base
import noesis.persistence.web_models


def transfer_sqlite(source, target):
    path = Path(source).resolve(strict=True)
    engine = create_engine(f'sqlite:///file:{quote(path.as_posix())}?mode=ro&uri=true')
    names = set(inspect(engine).get_table_names())
    counts = {}
    try:
        with engine.connect() as old, target.transaction() as new:
            for table in Base.metadata.sorted_tables:
                if new.execute(select(table).limit(1)).first():
                    raise ValueError('Target must be empty; use a new isolated database')
            for table in Base.metadata.sorted_tables:
                if table.name not in names or table.name == 'app_login_sessions': continue
                # SQLAlchemy applies JSON/datetime decoding using the canonical schema.
                rows = [dict(r) for r in old.execute(select(table)).mappings()]
                for row in rows:
                    for column in table.columns:
                        if isinstance(column.type, DateTime) and row.get(column.name) is not None:
                            row[column.name] = as_utc(row[column.name])
                if rows: new.execute(table.insert(), rows)
                counts[table.name] = len(rows)
            if target.engine.dialect.name == 'sqlite' and 'learning_fts' in names:
                for row in old.exec_driver_sql('SELECT entity_type,entity_id,learner_id,title,body,provenance FROM learning_fts'):
                    new.connection().exec_driver_sql('INSERT INTO learning_fts VALUES (?,?,?,?,?,?)', tuple(row))
        return counts
    finally:
        engine.dispose()
