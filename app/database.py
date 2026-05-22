
from pathlib import Path
import os

from sqlalchemy import create_engine
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "timetable.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# support common environment variable names for compatibility
database_url = (
    os.getenv("DATABASE_URL")
    or os.getenv("DB")
    or os.getenv("DATABASE_URI")
)
DATABASE_URL = database_url if database_url else f"sqlite:///{DB_PATH.as_posix()}"
try:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False} if not database_url else {},
        future=True,
    )
except ArgumentError as exc:
    raise RuntimeError(
        "Invalid database URL. Set DATABASE_URL to a valid SQLAlchemy connection string."
    ) from exc

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
