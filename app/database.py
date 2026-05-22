
from pathlib import Path
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "timetable.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

database_url = os.getenv("DATABASE_URL")
DATABASE_URL = database_url if database_url else f"sqlite:///{DB_PATH.as_posix()}"
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if not database_url else {},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
