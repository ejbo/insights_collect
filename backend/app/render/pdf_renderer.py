"""Markdown → PDF via weasyprint.

Pipeline: Markdown → HTML (via stdlib markdown lib if present, else simple) →
weasyprint HTML→PDF. CJK fonts come from the OS (Noto CJK on Linux/mac).
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_CSS = """
@page { size: A4; margin: 18mm 16mm 22mm 16mm; }
body { font-family: 'Noto Sans CJK SC', 'PingFang SC', 'Helvetica Neue', sans-serif;
       font-size: 11pt; line-height: 1.55; color: #1f2937; }
h1 { font-size: 22pt; margin: 0 0 8mm; border-bottom: 2px solid #2563eb; padding-bottom: 4mm; }
h2 { font-size: 16pt; margin: 8mm 0 4mm; color: #1d4ed8; }
h3 { font-size: 13pt; margin: 6mm 0 2mm; color: #4338ca; }
blockquote { border-left: 3px solid #6366f1; padding: 2mm 4mm; margin: 2mm 0;
             color: #374151; background: #f5f7ff; }
code { font-family: 'SFMono-Regular', monospace; background: #f3f4f6; padding: 0 2pt; border-radius: 2pt; }
ul, ol { margin: 2mm 0 4mm 6mm; }
li { margin-bottom: 1mm; }
hr { border: 0; border-top: 1px solid #e5e7eb; margin: 6mm 0; }
a { color: #2563eb; text-decoration: none; }
"""


def _md_to_html(md_text: str) -> str:
    try:
        import markdown  # type: ignore
        return markdown.markdown(
            md_text,
            extensions=["extra", "sane_lists", "tables", "toc"],
        )
    except Exception:  # noqa: BLE001
        # Fallback: very rough conversion (paragraphs + headers + bullets).
        from html import escape
        lines: list[str] = []
        for line in md_text.splitlines():
            if line.startswith("# "):
                lines.append(f"<h1>{escape(line[2:])}</h1>")
            elif line.startswith("## "):
                lines.append(f"<h2>{escape(line[3:])}</h2>")
            elif line.startswith("### "):
                lines.append(f"<h3>{escape(line[4:])}</h3>")
            elif line.startswith("- "):
                lines.append(f"<li>{escape(line[2:])}</li>")
            elif line.startswith("> "):
                lines.append(f"<blockquote>{escape(line[2:])}</blockquote>")
            elif line.strip() == "":
                lines.append("<br>")
            else:
                lines.append(f"<p>{escape(line)}</p>")
        return "\n".join(lines)


def render_pdf(md_text: str, output_path: Path, title: str = "Report") -> Path:
    from weasyprint import CSS, HTML  # type: ignore
    html_body = _md_to_html(md_text)
    html = (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
        f"</head><body>{html_body}</body></html>"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(target=str(output_path), stylesheets=[CSS(string=_CSS)])
    return output_path
