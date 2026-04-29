"""Render a `report_templates.prompt_template` (kind=ppt_outline) into a JSON dict.

We render the Jinja template into a JSON-string then parse — gives users full freedom
to design slide structures while keeping output strictly typed.
"""

import json
from typing import Any

from jinja2 import ChainableUndefined, Environment


def render_ppt_outline(template_str: str, ctx: dict[str, Any]) -> dict:
    env = Environment(undefined=ChainableUndefined, trim_blocks=True, lstrip_blocks=True)
    rendered = env.from_string(template_str).render(**ctx)
    try:
        return json.loads(rendered)
    except Exception as e:  # noqa: BLE001
        # Provide debuggable preview if user template is malformed.
        snippet = rendered[:500].replace("\n", " ⏎ ")
        raise ValueError(f"PPT outline JSON parse failed: {e}; preview: {snippet}") from e
