"""DB-first credential loading: read provider_credentials, fall back to .env.

Used at LangGraph node start: `creds = await load_credentials(session)` → maps provider
name to `{api_key, base_url, default_model, enabled}` for use by adapter constructors.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import models


@dataclass
class ProviderCreds:
    provider: str
    api_key: str
    base_url: str | None
    default_model: str | None
    enabled: bool

    @property
    def usable(self) -> bool:
        return self.enabled and bool(self.api_key)


_ENV_KEY_MAP = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "google_api_key",
    "grok": "xai_api_key",
    "perplexity": "perplexity_api_key",
    "qwen": "dashscope_api_key",
    "deepseek": "deepseek_api_key",
}


async def load_credentials(session: AsyncSession) -> dict[str, ProviderCreds]:
    settings = get_settings()
    rows = (await session.execute(select(models.ProviderCredential))).scalars().all()
    by_provider = {row.provider: row for row in rows}

    out: dict[str, ProviderCreds] = {}
    for provider, env_attr in _ENV_KEY_MAP.items():
        row = by_provider.get(provider)
        env_key = getattr(settings, env_attr, "") or ""
        if row is not None:
            api_key = row.api_key or env_key
            out[provider] = ProviderCreds(
                provider=provider,
                api_key=api_key,
                base_url=row.base_url,
                default_model=row.default_model,
                enabled=row.enabled and bool(api_key),
            )
        else:
            out[provider] = ProviderCreds(
                provider=provider,
                api_key=env_key,
                base_url=None,
                default_model=None,
                enabled=bool(env_key),
            )
    return out
