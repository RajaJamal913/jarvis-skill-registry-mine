"""
Database engine / session configuration.

DATABASE_URL controls the backend. Two modes are supported:

  * PostgreSQL (preferred, default via docker-compose):
        postgresql+psycopg2://user:pass@host:port/dbname

  * SQLite (used ONLY for the automated test suite - see README
    "Architecture Decisions" for the written justification required
    by the evaluation brief). Tests set DATABASE_URL to a sqlite
    file/memory URL before importing the app.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://jarvis:jarvis_dev_password@localhost:5432/jarvis_skills",
)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
