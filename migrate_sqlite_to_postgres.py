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
    allow_nonempty: bool = False,
) -> None:
    rows: Sequence[RowMapping] = src_conn.execute(src_table.select()).mappings().all()
    if not rows:
        print(f"  {table_name}: no rows")
        return

    existing = dst_conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
    if existing and not allow_nonempty:
        raise RuntimeError(
            f"Destination table '{table_name}' is not empty ({existing} rows). Remove data or choose an empty database."
        )

    print(f"  {table_name}: copying {len(rows)} rows")
    batch = [dict(row) for row in rows]
    dst_conn.execute(dst_table.insert(), batch)


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def reset_postgres_sequence(dst_conn: Connection, table_name: str, pk_column: str = "id") -> None:
    sequence_name = dst_conn.execute(
        text("SELECT pg_get_serial_sequence(:table_name, :pk_column)"),
        {"table_name": table_name, "pk_column": pk_column},
    ).scalar()
    if sequence_name is None:
        return

    quoted_table = _quote_ident(table_name)
    quoted_pk = _quote_ident(pk_column)
    dst_conn.execute(
        text(
            f"SELECT setval(:sequence_name, COALESCE((SELECT MAX({quoted_pk}) FROM {quoted_table}), 0), true)"
        ),
        {"sequence_name": sequence_name},
    )


def clear_destination_tables(dst_conn: Connection, table_names: Sequence[str]) -> None:
    table_list = ", ".join(_quote_ident(name) for name in table_names)
    dst_conn.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))


def migrate(sqlite_path: Path, postgres_url: str, force: bool = False) -> None:
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
        if force:
            print("Clearing destination tables...")
            clear_destination_tables(dst_conn, [table_name for table_name in TABLE_ORDER if table_name in dst_meta.tables])

        for table_name in TABLE_ORDER:
            if table_name not in src_meta.tables:
                print(f"  Skipping missing table in source: {table_name}")
                continue
            if table_name not in dst_meta.tables:
                raise RuntimeError(f"Destination table '{table_name}' does not exist.")
            copy_table(
                src_conn,
                dst_conn,
                src_meta.tables[table_name],
                dst_meta.tables[table_name],
                table_name,
                allow_nonempty=force,
            )

        print("Resetting Postgres serial sequences...")
        for table_name in TABLE_ORDER:
            reset_postgres_sequence(dst_conn, table_name)

    print("Migration complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copy local SQLite data into a Postgres database.")
    parser.add_argument("--sqlite-file", default="timetable.db", help="Path to local SQLite file")
    parser.add_argument("--postgres-url", required=True, help="Postgres DATABASE_URL")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Truncate destination tables before copying local data. This will overwrite existing remote data.",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_file).expanduser().resolve()
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite file not found: {sqlite_path}")

    migrate(sqlite_path, args.postgres_url, force=args.force)
