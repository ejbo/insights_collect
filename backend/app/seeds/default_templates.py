"""Day-1 内置三个报告模板：ICT 速览 / 学术综述 / 投资视角.

模板用 Jinja2 语法。可用变量（由 ReportComposer 注入）：
- title, time_range_start, time_range_end
- focus_topics: list[str]
- sections: list[Section]
    - section.topic_name
    - section.clusters: list[Cluster]
        - cluster.label, cluster.kind, cluster.summary_md
        - cluster.viewpoints: list[Viewpoint] (7 元组完整字段)
- top_experts: list[Expert]
- analysis: { consensus, dissent, spotlight, insight } (LLM 综合写)
"""

DEFAULT_TEMPLATES = [
    # ---- 1. ICT 速览风格（Markdown 报告 + PPT 大纲共用一份元素） ----
    {
        "name": "ICT 速览风格 · Markdown",
        "kind": "md_report",
        "is_default": True,
        "is_builtin": True,
        "description": "封面 → 各主题章节 → 每节内观点卡 → 章末共识/分歧总结。适合 ICT/科技产业打卡式速览。",
        "prompt_template": """# {{ title }}

**时间窗**：{{ time_range_start.strftime('%Y-%m-%d') }} ~ {{ time_range_end.strftime('%Y-%m-%d') }}
**焦点主题**：{{ focus_topics | join('、') }}

---

## 摘要

{{ analysis.executive_summary }}

---

{% for section in sections %}
## {{ loop.index }}. {{ section.topic_name }}

{% for cluster in section.clusters %}
### {{ cluster.label }}  ({{ cluster.kind }})

{{ cluster.summary_md }}

{% for v in cluster.viewpoints %}
- **{{ v.claim_who_role or v.expert_name }}** · *{{ v.claim_when.strftime('%Y-%m-%d') if v.claim_when else '时间未知' }}* · {{ v.claim_where or v.claim_medium or '场合未知' }}
  > {{ v.claim_quote or v.claim_what }}
  *—— [{{ v.source_domain or '来源' }}]({{ v.claim_source_url }})*

{% endfor %}
{% endfor %}

**本节小结**：{{ section.section_summary }}

---
{% endfor %}

## 综合分析

### 共识
{% for item in analysis.consensus %}- {{ item }}
{% endfor %}

### 分歧
{% for item in analysis.dissent %}- {{ item }}
{% endfor %}

### 重点关注
{% for item in analysis.spotlight %}- {{ item }}
{% endfor %}

### 启示
{% for item in analysis.insight %}- {{ item }}
{% endfor %}

---

## 附录 · 来源列表

{% for v in all_viewpoints %}- [{{ v.expert_name }} @ {{ v.claim_medium or v.claim_where }}]({{ v.claim_source_url }})
{% endfor %}
""",
        "jinja_vars": {
            "required": ["title", "focus_topics", "sections", "analysis"],
        },
    },
    {
        "name": "ICT 速览风格 · PPT 大纲",
        "kind": "ppt_outline",
        "is_default": True,
        "is_builtin": True,
        "description": "结构化 JSON：cover / section / viewpoint_card / analysis 四类 slide。喂给 Gamma/Tome。",
        "prompt_template": """{
  "meta": {
    "title": {{ title | tojson }},
    "subtitle": {{ (focus_topics | join('・')) | tojson }},
    "date_range": {{ (time_range_start.strftime('%Y-%m-%d') ~ ' ~ ' ~ time_range_end.strftime('%Y-%m-%d')) | tojson }}
  },
  "slides": [
    { "kind": "cover", "title": {{ title | tojson }}, "subtitle": {{ (focus_topics | join('・')) | tojson }} },
    { "kind": "executive_summary", "title": "摘要", "bullets": {{ analysis.executive_summary_bullets | tojson }} },
    {% for section in sections %}
    { "kind": "section", "title": {{ section.topic_name | tojson }} },
      {% for cluster in section.clusters %}
      { "kind": "cluster", "title": {{ cluster.label | tojson }}, "cluster_kind": {{ cluster.kind | tojson }}, "summary": {{ cluster.summary_md | tojson }} },
        {% for v in cluster.viewpoints %}
        { "kind": "viewpoint_card",
          "expert": {{ v.expert_name | tojson }},
          "role": {{ (v.claim_who_role or '') | tojson }},
          "when": {{ (v.claim_when.strftime('%Y-%m-%d') if v.claim_when else '') | tojson }},
          "venue": {{ (v.claim_where or v.claim_medium or '') | tojson }},
          "quote": {{ (v.claim_quote or v.claim_what) | tojson }},
          "claim_summary": {{ v.claim_what | tojson }},
          "source_url": {{ (v.claim_source_url or '') | tojson }} }{% if not loop.last %},{% endif %}
        {% endfor %}{% if not loop.last %},{% endif %}
      {% endfor %}{% if not loop.last %},{% endif %}
    {% endfor %},
    { "kind": "analysis", "title": "共识与分歧", "consensus": {{ analysis.consensus | tojson }}, "dissent": {{ analysis.dissent | tojson }} },
    { "kind": "analysis", "title": "重点 & 启示", "spotlight": {{ analysis.spotlight | tojson }}, "insight": {{ analysis.insight | tojson }} }
  ]
}
""",
        "jinja_vars": {
            "required": ["title", "focus_topics", "sections", "analysis"],
        },
    },
    # ---- 2. 学术综述风格 ----
    {
        "name": "学术综述风格 · Markdown",
        "kind": "md_report",
        "is_default": False,
        "is_builtin": True,
        "description": "摘要 → 文献综述（多视角对比）→ 启示与展望。适合做研究报告、学术分析。",
        "prompt_template": """# {{ title }}

**Time range**: {{ time_range_start.strftime('%Y-%m-%d') }} – {{ time_range_end.strftime('%Y-%m-%d') }}
**Topics**: {{ focus_topics | join('; ') }}

## Abstract

{{ analysis.executive_summary }}

## 1. Introduction

本综述围绕 {{ focus_topics | join('、') }} 主题，整合来自不同学者、机构与产业领袖的最新观点。

## 2. Literature Review

{% for section in sections %}
### 2.{{ loop.index }} {{ section.topic_name }}

{% for cluster in section.clusters %}
**{{ cluster.label }}**（{{ cluster.kind }}）：{{ cluster.summary_md }}

代表性观点：
{% for v in cluster.viewpoints %}
- *{{ v.expert_name }}* ({{ v.claim_who_role or 'N/A' }}, {{ v.claim_when.strftime('%Y') if v.claim_when else 'n.d.' }})——{{ v.claim_what }} ([source]({{ v.claim_source_url }}))
{% endfor %}

{% endfor %}
{% endfor %}

## 3. Discussion

### 3.1 共识
{% for item in analysis.consensus %}- {{ item }}
{% endfor %}

### 3.2 主要分歧
{% for item in analysis.dissent %}- {{ item }}
{% endfor %}

## 4. 启示与展望

{% for item in analysis.insight %}- {{ item }}
{% endfor %}

## References

{% for v in all_viewpoints %}- {{ v.expert_name }} ({{ v.claim_when.strftime('%Y') if v.claim_when else 'n.d.' }}). {{ v.claim_what }}. *{{ v.claim_medium or v.source_domain }}*. {{ v.claim_source_url }}
{% endfor %}
""",
        "jinja_vars": {
            "required": ["title", "focus_topics", "sections", "analysis"],
        },
    },
    # ---- 3. 投资视角 ----
    {
        "name": "投资视角 · Markdown",
        "kind": "md_report",
        "is_default": False,
        "is_builtin": True,
        "description": "执行摘要 → 关键人物观点 → 行业信号 → 风险与机会。适合投研分析。",
        "prompt_template": """# {{ title }} — Investment Memo

**Coverage**: {{ time_range_start.strftime('%Y-%m-%d') }} → {{ time_range_end.strftime('%Y-%m-%d') }}

## Executive Summary

{{ analysis.executive_summary }}

## Key Voices

{% for v in top_viewpoints %}
### {{ v.expert_name }} — {{ v.claim_who_role }}
> "{{ v.claim_quote or v.claim_what }}"

— {{ v.claim_where or v.claim_medium }} · {{ v.claim_when.strftime('%Y-%m-%d') if v.claim_when else '' }} · [link]({{ v.claim_source_url }})

**Take**: {{ v.claim_why_context or v.claim_what }}

{% endfor %}

## Signals

{% for section in sections %}
### {{ section.topic_name }}
{% for cluster in section.clusters %}
- **{{ cluster.label }}** ({{ cluster.kind }}): {{ cluster.summary_md }}
{% endfor %}
{% endfor %}

## Opportunities & Risks

**Opportunities**:
{% for item in analysis.spotlight %}- {{ item }}
{% endfor %}

**Risks / Watch-outs**:
{% for item in analysis.dissent %}- {{ item }}
{% endfor %}

## Outlook

{% for item in analysis.insight %}- {{ item }}
{% endfor %}
""",
        "jinja_vars": {
            "required": ["title", "focus_topics", "sections", "analysis", "top_viewpoints"],
        },
    },
]
