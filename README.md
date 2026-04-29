# Insights Collect — 多模型多 Agent 协同的专家观点收集与深度分析平台

**真正要解决的问题**：针对一个主题（如「Token 经济」「斯坦福 2026 AI 报告」「Pichai 十年复盘」），系统需要在一个**较宽时间窗内**（如近 30 天）通过 **多个搜索模型并行 + 多轮 agent 迭代**，**最大化召回**：
- 不止知名大咖（黄仁勋、Pichai），还要挖到「在该主题上有特定影响力但不广为关注」的人物——例如 Token 经济议题里的刘烈宏（国家数据局局长）、胡延平（上海财大特聘教授）、欧阳剑（昆仑芯 CEO）这类需要从「中国发展高层论坛」「央广财经」这类**事件/场合**反向挖出的声音。
- 每条观点结构化为 **7 元组**（基于新闻学 5W + 媒介 + 来源）：
  - **Who** = 专家姓名/角色 · **When** = 时间 · **Where** = 场合/地点 · **What** = 观点摘要 + 原话引用
  - **Medium/Event** = 论坛 / 采访栏目 / 文章 · **Source** = 链接 · **Why/Context** = 上下文背景（agent 能补就补）
- 跨源、跨语言、跨立场 max 召回，再由大模型做**深度分析**：共识/分歧映射、重点标注、启示提炼、整体总结——**不做简单情感分析**。

**自我进化**：每次 run 中发现的「好专家」「关键事件/论坛/采访栏目」「跑得好的 prompt skills」都沉淀进库，下次 run 直接复用 + 持续扩张关注面。一年后这套库会从 0 长成一个有领域 know-how 的资产。

**用户可定制 PPT 大纲模板**：所有报告模板（PPT 大纲、Markdown 章节风格）存在 DB 里，UI 可视化编辑、版本管理；触发报告时下拉选模板。Day-1 内置三个：「ICT 速览风格」「学术综述风格」「投资视角」。

**第一阶段实现**：用户在网页上输入主题列表 + 时间窗 + 选模板 → 跑完整多 agent 协同 → 拿到 Markdown 报告 + PPT 大纲 JSON + PDF。

**第二阶段功能**：APScheduler 定时任务、TopicDiscoverer 热度自动发现、interest_scopes 兴趣范围。Day-1 用户手动指定主题即可。

**API key 在网页端配置**：新增 `provider_credentials` 表 + `/settings` 页面，可视化配置 6 家 key、base_url、启用开关、连接测试按钮。`.env` 作为兜底（无 key → fallback）。改 key 不需要重启进程或改代码。

**输出形态**：① Markdown 报告（网页内可预览、可编辑） ② PPT 大纲 JSON（喂给 Gamma/Tome 等外部 PPT 生成器） ③ PDF 下载（weasyprint）。**不自己渲染 .pptx**。
---

## 系统架构

### 1. Provider 抽象层（6）

| Provider | 强项 | 调用方式 | 用在哪 |
|---|---|---|---|
| **Claude** (`claude-opus-4-7` / `claude-sonnet-4-6`) | 抽取 / 推理 / 长文档分析 | Anthropic SDK + `web_search_20260209` | 结构化抽取、深度分析、最终汇编 |
| **Gemini** (`gemini-2.5-pro`) | Google 索引覆盖最广，英文学术/报告 | google-genai + Google Search grounding | 学术报告、英文头部信源 |
| **OpenAI** (`gpt-5` / `gpt-5-mini`) | 综合搜索 + 推理 | openai SDK + web_search tool | 交叉验证、补充覆盖 |
| **Grok** (`grok-4`) | X / Twitter 实时圈子，企业家原话 | xAI SDK + Live Search | 黄仁勋/Musk 这类活跃在 X 的大咖 |
| **Perplexity** (`sonar-pro`) | 引用透明度顶级，专业网页 | Sonar API | 高质量带引用的事实抽取 |
| **Qwen / DeepSeek** (`qwen3-max` / `deepseek-v3.2`) | 中文互联网覆盖最深 | DashScope / DeepSeek API | 中国论坛、央媒、专家访谈（刘烈宏、胡延平这类） |

接口契约（[providers/base.py](backend/app/providers/base.py)）：
```python
class SearchProvider(Protocol):
    name: str
    async def search(query: str, time_window: TimeRange, lang: str) -> list[RawSnippet]
    async def structured_extract(content: str, schema: BaseModel) -> BaseModel
    async def analyze(prompt: str, context: list[str]) -> str
```
每次调用统一记录 token / cost / latency 到 `provider_calls` 表。

### 2. 多 Agent 编排：LangGraph 状态机

LangGraph 是当前 Python multi-agent 事实标准：原生支持 **并行 super-step**、**带 cycle 的反思循环**、**state 持久化（断点续跑）**、**LangSmith tracing**，且 LLM-provider 中立。FastAPI 只调用 `graph.ainvoke(state)` 触发，编排逻辑独立，未来可独立部署到 LangGraph Platform。

**主图（[agents/graph.py](backend/app/agents/graph.py)）**：

```
                  [ Planner ]
                       │
              拆解主题→子查询/语种/视角 + 选模板 + 选 skill
                       │
       ┌───────────────┼─────────────────────────┐
       ▼               ▼                         ▼
   parallel super-step (按 provider × 语种 fan-out)
   Claude · Gemini · OpenAI · Grok · Perplexity · Qwen/DeepSeek
       └───────────────┬─────────────────────────┘
                       ▼
                [ DedupMerger ]
            embedding 跨源合并、source-conflict 标注
                       │
                       ▼
        ┌─────────[ ExpertDiscoverer ]─────────┐
        │  (双向)                              │
        │  ① 主题→事件/论坛/采访 → 出席/受访人   │
        │  ② 主题→已知大咖列表 + agent 推荐补充  │
        │  ③ 跨 provider 提名打分               │
        └──────────────┬───────────────────────┘
                       ▼
              [ ViewpointExtractor ]
        每个 (专家, 主题) 对：原话引用 + 7 元组
                       ▼
                  [ Critic ]
        覆盖度评估：地域 / 立场 / 影响力层级 / 时段
                       │
              ┌────────┴────────┐
       cover OK│                │ 有缺口
              │                  ▼
              │            [ GapFiller ]
              │     用未用过的 provider/query 补搜
              │                  │
              │     ◄────────────┘  (回到 DedupMerger，最多 N 轮)
              ▼
            [ ClusterAnalyzer ]
   embedding 聚类 → LLM 写簇标签 + 共识/分歧/重点/启示分析
                       ▼
            [ KnowledgeWriter ]
   入库：experts / events / sources / viewpoints / topics（含 embedding）
                       ▼
            [ ReportComposer ]
   按 report_templates 选定的模板 → Markdown 报告 + PPT 大纲 JSON
                       ▼
            [ SkillUpdater ]
   评估本次跑得好的 prompt → 更新 skills 表（self-evolution）
```

关键设计：
- **并行 super-step**：6 个 provider × 多个子查询同时跑，LangGraph 自动 fan-out / fan-in
- **Critic ↔ GapFiller** 是带 cycle 的反思循环（最多 3 轮，由 Critic 判停）
- **State 持久化**用 LangGraph 的 `PostgresSaver`，跑到一半挂了可断点续跑
- **可观测**：LangSmith / 自建 `agent_runs` 表记录每节点的输入输出和 token

### 3. 数据模型（Postgres 16 + pgvector，**SQLModel** 定义）

| 表 | 关键字段 | 说明 |
|---|---|---|
| `experts` | id, name, name_zh, aliases[], bio, domains[], affiliations[], profile_urls[], influence_scores jsonb, embedding | `influence_scores` 按主题打分而非全局 |
| `expert_aliases` | expert_id, alias, lang | 中英文消歧 |
| `topics` | id, slug, name, parent_id, description, embedding | 主题树 |
| `events` | id, name, kind[forum/interview/podcast/keynote/paper], host, date, url, embedding | 论坛/采访栏目，跨 run 复用的 anchor |
| `sources` | id, domain, name, kind, lang, reliability_score | 媒体/平台元数据 |
| `viewpoints` | id, expert_id, event_id?, source_id, **claim_who_role**, **claim_when**, **claim_where**, **claim_what**, **claim_quote**, **claim_medium**, **claim_source_url**, **claim_why_context**, claim_lang, embedding, confidence, providers_seen[], ingested_at | **7 元组直白展开**为字段 |
| `viewpoint_topics` | viewpoint_id, topic_id, relevance | 多对多 |
| `skills` | id, name, kind[search/extract/analyze], domain, prompt_template, success_score, last_used_at, version | 沉淀的 prompt 模板，SkillUpdater 自动评估 |
| **`report_templates`** | id, name, kind[ppt_outline/md_report/section], prompt_template, jinja_vars jsonb, is_default, version, created_at | **用户可在 UI 编辑**；用 Jinja 模板，渲染时注入 `{{topic}}` `{{viewpoints}}` `{{cluster_label}}` 等 |
| `reports` | id, kind, title, focus_topics[], time_range, **template_id (fk → report_templates)**, status, md_path, outline_json_path, pdf_path | 报告记录所用模板 |
| `report_sections` | report_id, topic_id, cluster_label, cluster_kind[consensus/dissent/spotlight/insight], summary_md, viewpoint_ids[], order | `cluster_kind` 取代旧的情感标签 |
| `agent_runs` | id, report_id, graph_node, state_in, state_out, tokens, cost_usd, started_at, finished_at, error | 多轮 agent 的可观测层 |
| `provider_calls` | id, agent_run_id, provider, model, query, tokens, cost_usd, latency_ms | 细粒度成本/性能 |
| **`interest_scopes`** | id, name, description (NL), lang_pref[], providers_enabled[], schedule_cron, top_n_topics, last_run_at, is_active, created_at | **用户兴趣域**：自然语言+cron，触发 TopicDiscoverer |
| **`trending_topics`** | id, scope_id, run_at, topic, rationale, score, signal_breakdown jsonb, picked_for_report_id | 每次 discover 跑的产物（哪些主题被选中、依据何种信号） |

ORM 选型：**SQLModel**（Pydantic + SQLAlchemy 同源，模型 = DB 表 = API 响应 schema 一份代码），异步用 `sqlmodel.ext.asyncio`。

### 4. 输出层

- [render/markdown_renderer.py](backend/app/render/markdown_renderer.py)：从 `report_sections` + 选定模板渲染完整 MD（封面块、各主题章节、每个簇的「共识/分歧/重点/启示」、专家观点卡、附录来源列表）
- [render/ppt_outline_renderer.py](backend/app/render/ppt_outline_renderer.py)：按选定 PPT 大纲模板输出 JSON
  ```json
  { "slides": [
    {"kind": "cover", "title": "...", "subtitle": "...", "date_range": "..."},
    {"kind": "section", "title": "Token 经济"},
    {"kind": "viewpoint_card", "expert": "刘烈宏", "role": "国家数据局局长",
     "when": "2026-03-XX", "venue": "中国发展高层论坛 2026",
     "quote": "...", "claim_summary": "...", "source_url": "..."},
    {"kind": "analysis", "title": "共识与分歧", "bullets": [...], "highlights": [...]}
  ]}
  ```
- [render/pdf_renderer.py](backend/app/render/pdf_renderer.py)：weasyprint 把 Markdown→PDF
- [render/template_engine.py](backend/app/render/template_engine.py)：用 **Jinja2** 加载 `report_templates.prompt_template` 并渲染

**Day-1 内置 3 个模板**（seed 进 DB）：
1. **ICT 速览风格**：封面 → 主题分章 → 每章 3-5 张观点卡 → 章末「共识/分歧」总结一页
2. **学术综述风格**：摘要 → 文献综述（多视角对比） → 启示与展望
3. **投资视角**：执行摘要 → 关键人物观点 → 行业信号 → 风险与机会

### 5. 前端（Next.js 15 + shadcn/ui + TanStack Query）

| 页面 | 功能 |
|---|---|
| `/` Dashboard | 最近报告、跑批中 agent runs（实时 SSE 进度）、专家/事件/观点池规模 |
| `/reports/new` | 表单：标题、kind、focus_topics、time_range、**provider 多选**（默认全开）、**template 下拉**、最大反思轮数、cost 上限 |
| `/reports/[id]` | 左侧 Markdown 预览 + 右侧章节大纲 / 编辑器；顶部按钮：下载 PDF / 复制 PPT 大纲 JSON / 重渲染 |
| `/runs/[id]` | LangGraph 节点状态图 + 每节点 token/cost、可点开查看 in/out |
| `/experts` | 列表 + 单专家详情页（其历史观点流、主题影响力雷达） |
| `/events` | 论坛/采访列表，可手动新增 anchor（提示 agent 优先挖此事件） |
| `/topics` | 主题树编辑 |
| **`/templates`** | **报告模板编辑器**：Monaco editor + Jinja 变量提示 + 预览 + 保存版本 + 设默认 |
| **`/scopes`** | **兴趣范围管理**：自然语言描述 + cron 选择器（preset：每天 9 点 / 每周一 / 每月 1 号）+ 启用开关 + 上次跑历史 + trending_topics 列表展示 |
| `/skills` | 自我进化的 skill 库浏览与回滚 |

### 6. 调度 + 主题热度发现（Day-1 直接上）

**APScheduler 同进程跑**——本地单人零负担，未来要拆 worker 再换 Arq。

```python
@app.on_event("startup")
async def boot():
    for scope in await get_active_scopes():
        scheduler.add_job(run_scope, CronTrigger.from_crontab(scope.cron),
                          args=[scope.id], id=f"scope-{scope.id}")
    scheduler.start()
```

**TopicDiscoverer agent**（[agents/nodes/topic_discoverer.py](backend/app/agents/nodes/topic_discoverer.py)）——独立 LangGraph 子图，cron 触发：

```
[ ScopeLoader ] → 读 interest_scope.description + lang_pref + providers
       │
       ▼
[ TrendingSignalCollector ] (parallel)
   ┌── Grok: scope 内 X 高互动话题
   ├── Gemini: Google Trends rising queries
   ├── Perplexity: HN / 主流媒体头条
   ├── Qwen/DeepSeek: 微博 / 知乎 / 央媒头条
   └── DB Query: 近 7 天 viewpoint 增长 top topics
       │
       ▼
[ TrendingRanker ] LLM 综合 → top_n 热点子主题 + rationale + signal score
       │
       ▼
[ ReportFanOut ] → 对每个热点 invoke 主图 ReportComposer
```

**用户体验链**：
1. UI `/scopes` 创建一个 "AI 方向" scope，描述 + 选 cron `0 9 * * 1`（每周一上午 9 点）
2. 系统自动按 cron 跑 → discover top 5 热点 → 每个跑完整 ReportComposer
3. Dashboard 通知 / 邮件（可选，后期）
4. 用户也可手动「立即跑一次此 scope」

**频率推荐 preset（UI 给选项）**：
- daily 09:00（日报）
- weekly 周一 09:00（周报）
- monthly 1 号 09:00（月报）

**也保留即时手动模式**：`/reports/new` 直接填 `focus_topics` 跑，不依赖 scope。

### 7. 部署：Docker Compose + 本地裸装双轨

- **Docker Compose**（云上 / 一键启动）：postgres+pgvector 容器、backend、frontend、（可选）pgadmin
- **本地裸装**（开发更快）：`brew install postgresql@16 pgvector` → `uv run uvicorn` + `pnpm dev`
- 配置统一走 `.env`，两种模式只是 `DATABASE_URL` 指向不同（容器内 hostname vs `localhost`）

---

## 项目骨架

```
/Users/jzl19991121/Projects/insights_collect/
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI 入口（仅 HTTP 层）
│   │   ├── config.py                   # pydantic-settings
│   │   ├── db/{models.py, session.py}  # SQLModel 模型
│   │   ├── schemas/                    # Pydantic LLM 结构化输出 schema
│   │   ├── api/{reports,experts,events,topics,viewpoints,runs,skills,providers,templates}.py
│   │   ├── providers/                  # 6 家 adapter
│   │   │   ├── base.py
│   │   │   ├── anthropic_provider.py
│   │   │   ├── gemini_provider.py
│   │   │   ├── openai_provider.py
│   │   │   ├── grok_provider.py
│   │   │   ├── perplexity_provider.py
│   │   │   └── qwen_provider.py
│   │   ├── agents/
│   │   │   ├── state.py                # 主 State TypedDict
│   │   │   ├── graph.py                # LangGraph 主图组装
│   │   │   ├── nodes/
│   │   │   │   ├── planner.py
│   │   │   │   ├── multi_search.py     # parallel fan-out 给 6 家 provider
│   │   │   │   ├── dedup_merger.py
│   │   │   │   ├── expert_discoverer.py
│   │   │   │   ├── viewpoint_extractor.py
│   │   │   │   ├── critic.py
│   │   │   │   ├── gap_filler.py
│   │   │   │   ├── cluster_analyzer.py
│   │   │   │   ├── knowledge_writer.py
│   │   │   │   ├── report_composer.py
│   │   │   │   └── skill_updater.py
│   │   │   └── checkpointer.py         # PostgresSaver（断点续跑）
│   │   ├── render/
│   │   │   ├── template_engine.py      # Jinja2
│   │   │   ├── markdown_renderer.py
│   │   │   ├── ppt_outline_renderer.py
│   │   │   └── pdf_renderer.py
│   │   ├── seeds/
│   │   │   └── default_templates.py    # 三个内置模板
│   │   └── scheduling/apscheduler_jobs.py
│   ├── alembic/                        # 迁移
│   ├── pyproject.toml                  # uv 管理
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── app/{page,reports,experts,events,topics,viewpoints,runs,skills,templates}/...
│   ├── components/{ReportPreview,RunGraph,ProviderPicker,TemplatePicker,TemplateEditor,ExpertCard,ViewpointCard}.tsx
│   ├── lib/{api,sse}.ts
│   └── package.json
├── docker-compose.yml                  # postgres+pgvector, backend, frontend
└── README.md                           # 两种启动方式都给步骤
```

---

## 实施阶段（合并版）

### Phase 1 — Day-1 完整多 agent 系统 + 主题热度发现 + 定时
1. 项目骨架 + `pyproject.toml`(uv) + `package.json`(pnpm) + `.env.example` + `docker-compose.yml` + README（双轨启动）
2. SQLModel 全表 + Alembic 首次迁移 + 种子（3 个内置 `report_templates` + 5-10 个 `events` + 1 个示例 `interest_scope`）
3. 6 家 Provider adapter（统一接口）
4. LangGraph 主图：Planner → MultiSearch(6 并行) → DedupMerger → ExpertDiscoverer → ViewpointExtractor → Critic ↔ GapFiller(≤3 轮) → ClusterAnalyzer → KnowledgeWriter → ReportComposer
5. LangGraph 子图：**TopicDiscoverer**（ScopeLoader → TrendingSignalCollector(并行) → TrendingRanker → ReportFanOut）
6. PostgresSaver 接入（断点续跑）
7. Renderer 三件套（Jinja 模板引擎 + Markdown + PPT 大纲 JSON + PDF）
8. **APScheduler 同进程**：startup 读 active scopes 注册 cron
9. FastAPI 全部路由（含 `/scopes` `/templates`）+ SSE 进度推送
10. Next.js 前端：Dashboard / 新建报告 / 报告详情 / 运行图 / 模板编辑器 / 兴趣范围管理
11. 端到端跑通：① 手动触发 ICT 报告 验收 ② 创建 scope 触发 cron / 立即跑 验收

### Phase 2 — 自我进化与数据看板
12. SkillUpdater 节点 + skill 自动评分回写
13. 后台 ExpertExpander：周期性扩充专家、抓增量观点
14. 数据看板：观点/专家增长曲线、主题热度、provider 命中率
15. 邮件 / 推送通知（scope 跑完自动发）

---

## 关键依赖

- `langgraph` + `langgraph-checkpoint-postgres`
- `sqlmodel` + `pgvector` + Alembic + `asyncpg`
- `anthropic` `google-genai` `openai` `xai-sdk` `dashscope` + `httpx`（Perplexity）
- `jinja2`（模板）
- `weasyprint`（PDF）
- `apscheduler`
- `pydantic` v2
- 前端：Next.js 15、shadcn/ui、TanStack Query、`react-markdown`、Monaco editor（模板编辑器）

---

## 验证方法

**Phase 1 完成后**：

1. 启动（任选一种）：
   - Docker：`docker compose up`
   - 裸装：`brew services start postgresql@16` → `uv run alembic upgrade head` → `uv run uvicorn app.main:app` → `pnpm dev`
2. 浏览器开 `/templates`：确认三个内置模板存在，可编辑保存版本
3. 浏览器开 `/reports/new` 提交：
   - title: `ICT 产业打卡观点总结`
   - focus_topics: `["Token 经济", "黄仁勋", "斯坦福 2026 AI 报告", "Pichai 十年复盘"]`
   - time_window: 近 30 天
   - providers: 全选 6 家
   - template: 「ICT 速览风格」
4. 跳到 `/reports/[id]`，左侧 Markdown 预览出现：
   - 4 个一级章节，每章节内若干「共识/分歧/重点/启示」子簇
   - 每条观点卡含 7 元组完整字段
5. 在 `/runs/[id]` 看 LangGraph 节点流图（含 Critic ↔ GapFiller 反思循环至少 1 轮），每节点 token/cost 透明
6. 「中国发展高层论坛」类事件应被 ExpertDiscoverer 命中并写入 `events` 表
7. 刘烈宏 / 胡延平 / 欧阳剑这类长尾人物应被发现（主要靠 Qwen/DeepSeek + Perplexity 命中）
8. 多家命中的观点 `confidence > 0.8`、`providers_seen` 长度 ≥ 3
9. 点「下载 PDF」拿到 PDF；点「复制 PPT 大纲 JSON」拿到结构化数组；JSON 喂 Gamma 验证可直接用
10. 切换模板（如「投资视角」）重渲染，对比输出风格差异

**Phase 2 完成后**：

11. 跑同领域第二个主题，观察 `skills` 表里高分 prompt 自动被复用
12. APScheduler 周一自动跑「ICT 周报」，无需人工介入产出 Markdown + PDF

---

## 关键风险 & 应对

| 风险 | 应对 |
|---|---|
| 多源召回导致同观点不同表述满天飞 | DedupMerger 用 embedding 相似度（>0.88）合并，`providers_seen` 累加 |
| 长尾专家（刘烈宏类）幻觉风险高 | 必须有 source_url 且能打开（HTTP 200 + 内容含本人名）才入库；多家未命中→低 confidence 不进主报告 |
| 6 家 API 成本失控 | 每个 report run 设 `max_tokens` / `max_provider_calls` / `cost_cap_usd`；超限自动降级 |
| LangGraph 反思循环死循环 | Critic 强制最多 3 轮，每轮必须报告「相比上轮新增覆盖」否则停 |
| 中文专家英文 provider 搜不到 | Planner 阶段按语种生成查询，Qwen/DeepSeek/Perplexity（中文）专门负责中文圈 |
| 事件 anchor 起步空、效果差 | seeds 阶段手动种 5-10 个高频事件（中国发展高层论坛、Stratechery、a16z Podcast、Stanford HAI、All-In Pod 等），后续 agent 自动扩充 |
| 用户改坏模板 | `report_templates.version` 自动递增，UI 支持回滚到任意版本；is_default 内置三个不可删 |

---

## Patch v0.1.1 — 实时可视化 + 代码端 provider 验证

### Problem
`MultiSearch` 节点用 `asyncio.gather` 等所有 (sub_query × provider) 任务一起返回。30+ 个 task 中有一个 HTTP 挂住，其余全陪跑；`provider_calls` 也是节点全部完成后才落库；又缺单次调用 timeout——结果就是用户盯着一个长跑的 MultiSearch 节点完全不知道还活着没。

### Fix（6 处变更）

1. **流式落库 ProviderCall** — [agents/nodes/multi_search.py](backend/app/agents/nodes/multi_search.py)
   - `asyncio.gather` → `asyncio.as_completed`
   - 每个 task 完成（不论成败）**立即** INSERT `ProviderCall` 行（含 `report_id`）
   - 报告详情页已有 3s SWR 轮询 `/api/runs/report/{id}/provider-calls`——改完后即时显示每条调用

2. **单次调用超时** — `multi_search.py`
   - 每个 `prov.search(...)` 包 `asyncio.wait_for(..., timeout=PROVIDER_CALL_TIMEOUT_S)`
   - 超时写一条 `success=False, error="timeout"` 的 ProviderCall 行，**不阻塞其他**
   - 默认 90s，`.env` 可调

3. **配置项** — [config.py](backend/app/config.py) + [.env.example](backend/.env.example)
   - 新增 `PROVIDER_CALL_TIMEOUT_S=90`

4. **Smoke-test 端点** — 代码端验证 provider 真能工作
   - `POST /api/settings/providers/{provider}/smoke`
   - Body: `{query?, lang?, days?, max_results?}`（全部可选，有默认值）
   - 跑一次真 `provider.search()`（60s 超时），返回：
     ```json
     {
       "success": true,
       "duration_ms": 8420,
       "snippets_count": 5,
       "sample": [{"title": "...", "url": "...", "snippet": "...", "source_domain": "..."}],
       "trace": {"provider": "...", "model": "...", "tokens_input": 234, "tokens_output": 1820, "cost_usd": 0.012, "latency_ms": 8420}
     }
     ```
   - 区别于现有 `/test`（仅 1-token analyze ping，验 key 有效性）：smoke 验**完整搜索链路**

5. **前端 /settings 页面** — 每张 provider 卡片加 "Smoke search" 按钮
   - 点击展开 inline 输入框（默认 query 已填）→ Run → 显示返回的 sample titles + 耗时 + tokens + cost
   - 与 "Test connection" 并存（前者快验 key、后者验真实可用）

6. **CLI 兜底** — [backend/app/tools/smoke.py](backend/app/tools/smoke.py)（新文件）
   - `docker exec insights-backend python -m app.tools.smoke` 一次性测所有已启用 provider，打表
   - UI 不通时也能调试

### 验证步骤
1. `docker compose restart backend` 重启
2. `/settings` 页面，每张配了 key 的 provider 卡点 "Smoke search" → 5-15s 内出 snippets 数 + sample
3. 故意把某个 provider 的 base_url 设成 `https://invalid.example.com` → 90s 后看到 timeout 错误，**其他 provider 不受影响**
4. 新建报告 → 报告详情页右侧 Provider calls 列表**边跑边出现**（而非一次性等几分钟才弹一堆）
5. CLI: `docker exec insights-backend python -m app.tools.smoke` → 终端打印 7 行表格
