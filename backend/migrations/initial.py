from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models

# create_all 只建新表，不会给既有库补列；这里做轻量幂等升级。
ADDED_COLUMNS = {
    'datasets': [
        ('station_id', 'INTEGER'),
        ('generation', 'INTEGER'),
        ('snapshot_id', 'INTEGER'),
    ],
    'jobs': [
        ('station_code', "VARCHAR(80) DEFAULT ''"),
        ('dataset_generation', 'INTEGER'),
        ('dataset_checksum', "VARCHAR(64) DEFAULT ''"),
    ],
}


def _upgrade_columns():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, columns in ADDED_COLUMNS.items():
            if table not in tables:
                continue
            existing = {column['name'] for column in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))


def migrate():
    Base.metadata.create_all(engine)
    _upgrade_columns()


if __name__ == '__main__':
    migrate()
