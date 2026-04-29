"""Tiny wrapper around Jinja2 used by all renderers.

We render strings (templates stored in DB) rather than file system templates so user-edited
templates take effect immediately.
"""

from typing import Any

from jinja2 import Environment, StrictUndefined, select_autoescape

_env = Environment(
    autoescape=select_autoescape([]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    enable_async=False,
    extensions=[],
)


def render_template(template_str: str, ctx: dict[str, Any]) -> str:
    template = _env.from_string(template_str)
    return template.render(**ctx)
