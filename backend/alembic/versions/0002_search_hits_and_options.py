"""add search_results table + reports.providers_options + provider_calls.extra

Revision ID: 0002_search_hits
Revises: 0001_initial
Create Date: 2026-04-29

NOTE: the upgrade is idempotent. 0001 calls SQLModel.metadata.create_all(),
which already builds every table/column from the *current* model — so on a
fresh DB the columns this migration adds may already exist. Using PostgreSQL's
`IF NOT EXISTS` keeps the migration safe to re-run on first boot.
"""
from alembic import op

revision = "0002_search_hits"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. providers_options on reports (jsonb, holds per-provider knobs)
    op.execute(
        "ALTER TABLE reports ADD COLUMN IF NOT EXISTS providers_options JSONB"
    )

    # 2. extra on provider_calls (jsonb — citations/search results metadata, etc.)
    op.execute(
        "ALTER TABLE provider_calls ADD COLUMN IF NOT EXISTS extra JSONB"
    )

    # 3. search_results table — raw web_search / web_fetch hits
    op.execute("""
        CREATE TABLE IF NOT EXISTS search_results (
            id               SERIAL PRIMARY KEY,
            report_id        INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            provider_call_id INTEGER          REFERENCES provider_calls(id) ON DELETE SET NULL,
            provider         VARCHAR(64)  NOT NULL,
            kind             VARCHAR(32)  NOT NULL DEFAULT 'web_search',
            query            TEXT,
            url              VARCHAR(2048),
            title            VARCHAR(1024),
            snippet          TEXT,
            source_domain    VARCHAR(255),
            page_age         VARCHAR(64),
            citations        JSONB,
            extra            JSONB,
            created_at       TIMESTAMP DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_search_results_report_id "
        "ON search_results (report_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_search_results_provider_call_id "
        "ON search_results (provider_call_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_search_results_provider "
        "ON search_results (provider)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_search_results_url "
        "ON search_results (url)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_search_results_source_domain "
        "ON search_results (source_domain)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS search_results")
    op.execute("ALTER TABLE provider_calls DROP COLUMN IF EXISTS extra")
    op.execute("ALTER TABLE reports DROP COLUMN IF EXISTS providers_options")
