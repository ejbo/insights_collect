"""add search_results table + reports.providers_options + provider_calls.extra

Revision ID: 0002_search_hits
Revises: 0001_initial
Create Date: 2026-04-29
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_search_hits"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. providers_options on reports (jsonb, holds per-provider knobs)
    op.add_column(
        "reports",
        sa.Column("providers_options", JSONB, nullable=True),
    )

    # 2. extra on provider_calls (jsonb — citations/search results metadata, etc.)
    op.add_column(
        "provider_calls",
        sa.Column("extra", JSONB, nullable=True),
    )

    # 3. search_results table — raw web_search / web_fetch hits
    op.create_table(
        "search_results",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.Integer,
                  sa.ForeignKey("reports.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("provider_call_id", sa.Integer,
                  sa.ForeignKey("provider_calls.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        sa.Column("provider", sa.String(length=64), nullable=False, index=True),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="web_search"),
        sa.Column("query", sa.Text, nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True, index=True),
        sa.Column("title", sa.String(length=1024), nullable=True),
        sa.Column("snippet", sa.Text, nullable=True),
        sa.Column("source_domain", sa.String(length=255), nullable=True, index=True),
        sa.Column("page_age", sa.String(length=64), nullable=True),
        sa.Column("citations", JSONB, nullable=True),
        sa.Column("extra", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("search_results")
    op.drop_column("provider_calls", "extra")
    op.drop_column("reports", "providers_options")
