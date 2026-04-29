"""initial schema with pgvector + seeds

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-29
"""
from alembic import op
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from app.db import models  # noqa: F401  -- registers all tables on metadata
from app.seeds.runner import seed_all

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    bind = op.get_bind()
    SQLModel.metadata.create_all(bind=bind)
    with Session(bind=bind) as session:
        seed_all(session)


def downgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.drop_all(bind=bind)
