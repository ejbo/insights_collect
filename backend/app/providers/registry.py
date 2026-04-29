"""Provider registry — instantiates the 6 (actually 7 with DeepSeek) adapters from credentials."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import SearchProvider
from app.providers.credentials import load_credentials
from app.providers.gemini_provider import GeminiProvider
from app.providers.grok_provider import GrokProvider
from app.providers.openai_compat_provider import DeepSeekProvider, QwenProvider
from app.providers.openai_provider import OpenAIProvider
from app.providers.perplexity_provider import PerplexityProvider

_FACTORY: dict[str, type[SearchProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "grok": GrokProvider,
    "perplexity": PerplexityProvider,
    "qwen": QwenProvider,
    "deepseek": DeepSeekProvider,
}


async def build_providers(session: AsyncSession) -> dict[str, SearchProvider]:
    creds = await load_credentials(session)
    out: dict[str, SearchProvider] = {}
    for provider_name, factory in _FACTORY.items():
        c = creds.get(provider_name)
        if c is None or not c.usable:
            continue
        out[provider_name] = factory(
            api_key=c.api_key,
            base_url=c.base_url,
            default_model=c.default_model,
        )
    return out


def list_providers() -> list[str]:
    return list(_FACTORY.keys())
