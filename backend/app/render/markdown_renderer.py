"""Render a `report_templates.prompt_template` (kind=md_report) into the final Markdown."""

from typing import Any

from app.render.template_engine import render_template


def render_markdown(template_str: str, ctx: dict[str, Any]) -> str:
    # Best-effort: tolerate missing fields by relaxing strict-undefined for now via try.
    try:
        return render_template(template_str, ctx)
    except Exception:
        # Fall back to a minimal template so we never produce nothing.
        from jinja2 import Environment, ChainableUndefined
        env = Environment(undefined=ChainableUndefined, trim_blocks=True, lstrip_blocks=True)
        return env.from_string(template_str).render(**ctx)
