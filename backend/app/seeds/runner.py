"""Idempotent seeder: insert/update built-in templates and seed events."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.seeds.default_events import DEFAULT_EVENTS
from app.seeds.default_templates import DEFAULT_TEMPLATES


def seed_default_templates(session: Session) -> None:
    for tpl in DEFAULT_TEMPLATES:
        existing = session.execute(
            select(models.ReportTemplate).where(
                models.ReportTemplate.name == tpl["name"],
                models.ReportTemplate.is_builtin.is_(True),
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(models.ReportTemplate(**tpl))
        else:
            # Only refresh built-in body unless user has edited (version > 1)
            if existing.version == 1:
                existing.prompt_template = tpl["prompt_template"]
                existing.description = tpl.get("description")
                existing.kind = tpl["kind"]
                existing.is_default = tpl.get("is_default", False)


def seed_default_events(session: Session) -> None:
    for ev in DEFAULT_EVENTS:
        existing = session.execute(
            select(models.Event).where(models.Event.name == ev["name"])
        ).scalar_one_or_none()
        if existing is None:
            session.add(models.Event(**ev))


def seed_default_provider_credentials(session: Session) -> None:
    """Pre-populate empty credential rows for all 6 providers so /settings UI shows them."""
    providers = [
        ("anthropic", "claude-opus-4-7"),
        ("openai", "gpt-5"),
        ("gemini", "gemini-2.5-pro"),
        ("grok", "grok-4"),
        ("perplexity", "sonar-pro"),
        ("qwen", "qwen3-max"),
        ("deepseek", "deepseek-v3.2"),
    ]
    for provider, default_model in providers:
        existing = session.execute(
            select(models.ProviderCredential).where(
                models.ProviderCredential.provider == provider
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(models.ProviderCredential(
                provider=provider,
                api_key="",
                default_model=default_model,
                enabled=False,
            ))


def seed_all(session: Session) -> None:
    seed_default_templates(session)
    seed_default_events(session)
    seed_default_provider_credentials(session)
    session.commit()
