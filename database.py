from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from typing import AsyncGenerator
from sqlalchemy import create_engine
import logging

class Base(DeclarativeBase):
    pass

DATABASE_URL = "duckdb:///data/beeview.duckdb"
engine = create_engine(DATABASE_URL, echo=False)  # Make sure echo=False
SessionLocal = sessionmaker(bind=engine)

# Create tables if they don't exist
from models import Base
Base.metadata.create_all(engine)

def get_session():
    with SessionLocal() as session:
        yield session
