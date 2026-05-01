"""Helper for picking the 'main model' used by every non-search node.

multi_search uses the providers list with their respective web_search tools.
Everything else (Planner, ExpertDiscoverer, ViewpointExtractor, ClusterAnalyzer,
ReportComposer, …) uses ONE model — set on `state.main_model`.
"""

from __future__ import annotations

from typing import Any

from app.providers.base import SearchProvider


_FALLBACK_ORDER = ["openai", "anthropic", "gemini", "deepseek", "qwen", "perplexity", "grok"]


def pick_main_model(
    providers: dict[str, SearchProvider],
    state: dict[str, Any],
) -> tuple[SearchProvider | None, str | None]:
    """Returns (provider_instance, model_id_override).

    Falls back through `_FALLBACK_ORDER` if the requested main model's provider
    has no configured key.
    """
    cfg = state.get("main_model") or {}
    want_provider = cfg.get("provider") or "openai"
    want_model = cfg.get("model") or None

    if want_provider in providers:
        return providers[want_provider], want_model

    # Fallback: same model id won't apply to a different provider, so we drop it.
    for name in _FALLBACK_ORDER:
        if name in providers:
            return providers[name], None
    if providers:
        return next(iter(providers.values())), None
    return None, None
