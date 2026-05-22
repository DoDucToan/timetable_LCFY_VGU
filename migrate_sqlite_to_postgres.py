import argparse
from pathlib import Path
from typing import Sequence

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.sql.schema import Table

TABLE_ORDER = [
    "cycle",
    "timetable",
    "group_tag",
    "study_program",
    "course_tag",
    "room",
    "timeslot",
    "teacher",
    "course",
    "study_program_has_course",
    "group_tbl",
    "group_has_study_program",
    "course_for_group_tag",
    "course_for_group_only",
    "teacher_course_tag",
    "class",
]


def copy_table(
    src_conn: Connection,
    dst_conn: Connection,
    src_table: Table,
    dst_table: Table,
    table_name: str,
) -> None:
    rows: Sequence[RowMapping] = src_conn.execute(src_table.select()).mappings().all()
    if not rows:
        print(f"  {table_name}: no rows")
        return

    existing = dst_conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
    if existing:
        raise RuntimeError(
            f"Destination table '{table_name}' is not empty ({existing} rows). Remove data or choose an empty database."
        )

    print(f"  {table_name}: copying {len(rows)} rows")
    batch = [dict(row) for row in rows]
    dst_conn.execute(dst_table.insert(), batch)


def migrate(sqlite_path: Path, postgres_url: str) -> None:
    sqlite_url = f"sqlite:///{sqlite_path.as_posix()}"
    src_engine = create_engine(sqlite_url, future=True)
    dst_engine = create_engine(postgres_url, future=True)

    src_meta = MetaData()
    dst_meta = MetaData()
    src_meta.reflect(bind=src_engine)
    dst_meta.reflect(bind=dst_engine)

    print("Creating missing destination tables...")
    # Create tables if needed by reflecting metadata from the app models
    from app.models import Base

    Base.metadata.create_all(dst_engine)
    dst_meta.reflect(bind=dst_engine)

    with src_engine.connect() as src_conn, dst_engine.begin() as dst_conn:
        for table_name in TABLE_ORDER:
            if table_name not in src_meta.tables:
                print(f"  Skipping missing table in source: {table_name}")
                continue
            if table_name not in dst_meta.tables:
                raise RuntimeError(f"Destination table '{table_name}' does not exist.")
            copy_table(src_conn, dst_conn, src_meta.tables[table_name], dst_meta.tables[table_name], table_name)

    print("Migration complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copy local SQLite data into a Postgres database.")
    parser.add_argument("--sqlite-file", default="timetable.db", help="Path to local SQLite file")
    parser.add_argument("--postgres-url", required=True, help="Postgres DATABASE_URL")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_file).expanduser().resolve()
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite file not found: {sqlite_path}")

    migrate(sqlite_path, args.postgres_url)
