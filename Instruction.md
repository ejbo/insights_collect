# Insights Collect

多模型多 Agent 协同的专家观点收集与深度分析平台。

输入主题（如「Token 经济」「斯坦福 2026 AI 报告」）→ 7 家 LLM 并行搜索 + LangGraph 多 agent 编排 → 输出结构化 Markdown 报告 + PPT 大纲 JSON + PDF。

---

## 目录

- [核心特性](#核心特性)
- [启动方式](#启动方式)
  - [方案 A · Docker Compose 一键起](#方案-a-docker-compose-一键起)
  - [方案 B · 本地裸装（开发更快）](#方案-b-本地裸装开发更快)
- [配置参数](#配置参数)
- [数据库连接位置](#数据库连接位置)
- [使用流程](#使用流程)
- [项目结构](#项目结构)
- [Agent 工作流](#agent-工作流)
- [常见问题](#常见问题)

---

## 核心特性

- **7 家搜索 / LLM provider 并行**：Claude · GPT-5 · Gemini · Grok · Perplexity · Qwen · DeepSeek
- **多 Agent 协同（LangGraph）**：
  Planner → MultiSearch（并行 fan-out）→ DedupMerger → ExpertDiscoverer → ViewpointExtractor → ClusterAnalyzer → KnowledgeWriter → ReportComposer
- **专家观点结构化为 7 元组**：Who · When · Where · What · Medium · Source · Why
- **数据自动积累**：experts / events / sources / viewpoints 跨 run 共享，越用越聪明（事件库已预置 10 个 anchor，如「中国发展高层论坛」「GTC」「Stanford HAI」「央广财经」「a16z Podcast」等）
- **报告模板用户可定制**：Jinja2 模板，UI 编辑，4 个内置（ICT 速览 MD + ICT 速览 PPT 大纲 + 学术综述 + 投资视角）
- **API key 在网页端配置**（不用改 .env / 不用改代码）
- **输出**：Markdown 报告（网页内预览 + 编辑）+ PPT 大纲 JSON + PDF 下载

---

## 启动方式

### 方案 A · Docker Compose 一键起

最简单，适合云上 / 服务器 / 第一次体验。

```bash
# 1) 复制 env 文件
cp backend/.env.example backend/.env

# 2) 启动整套（Postgres + 后端 + 前端）
docker compose up
```

服务地址：

| 服务 | 地址 |
|---|---|
| 前端 UI | <http://localhost:3000> |
| 后端 API | <http://localhost:8000> · 健康检查 <http://localhost:8000/health> · OpenAPI <http://localhost:8000/docs> |
| Postgres | `localhost:5432` · user `insights` · password `insights` · db `insights_collect` |

⚠️ **首次启动 backend 会自动跑 `alembic upgrade head`** 创建表 + 启用 `vector` 扩展 + 写入 4 个内置模板和 10 个种子事件。

不需要在 `.env` 里填任何 API key 也能启动；启动后到 <http://localhost:3000/settings> 配置即可。

### 方案 B · 本地裸装（开发更快）

前置依赖：

- Python ≥ 3.12
- Node ≥ 20，pnpm
- Postgres ≥ 16 + pgvector 扩展
- macOS 推荐用 [Homebrew](https://brew.sh)；Linux 用 apt

```bash
# 1) 安装 Postgres + pgvector
brew install postgresql@16 pgvector
brew services start postgresql@16

# 创建数据库 + 用户 + 启用 vector 扩展
createuser -s insights || true
psql postgres -c "ALTER USER insights WITH PASSWORD 'insights';"
createdb -O insights insights_collect
psql insights_collect -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 2) 后端
cd backend
cp .env.example .env
# 用编辑器打开 backend/.env，至少改 DATABASE_URL 指向本地（默认即可）
# 可以先不填 API key，后面在 /settings 页面填

# 用 uv（推荐）或 pip
pip install uv
uv venv
source .venv/bin/activate
uv pip install -e .

# 跑迁移（创建所有表 + 种子）
alembic upgrade head

# 启动后端
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 3) 另开一个终端，跑前端
cd frontend
pnpm install
pnpm dev
```

打开 <http://localhost:3000>。

---

## 配置参数

所有配置在 [backend/.env](backend/.env)（从 `.env.example` 复制）。**API key 不必在这里填**，可在 UI 里配置；这里的值作为 fallback。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_NAME` | `insights-collect` | 应用名（仅用于健康检查显示） |
| `APP_ENV` | `dev` | 环境标识 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| **`DATABASE_URL`** | `postgresql+asyncpg://insights:insights@localhost:5432/insights_collect` | **后端运行时连接 DB 的 URL**（async） |
| **`DATABASE_URL_SYNC`** | `postgresql://insights:insights@localhost:5432/insights_collect` | **Alembic / LangGraph PostgresSaver 用的同步 URL** |
| `STORAGE_DIR` | `./storage` | 生成文件根目录 |
| `REPORTS_DIR` | `./storage/reports` | Markdown 输出目录 |
| `PDFS_DIR` | `./storage/pdfs` | PDF 输出目录 |
| `OUTLINES_DIR` | `./storage/outlines` | PPT 大纲 JSON 目录 |
| `ANTHROPIC_API_KEY` | _空_ | Claude key（fallback） |
| `OPENAI_API_KEY` | _空_ | OpenAI key（fallback） |
| `GOOGLE_API_KEY` | _空_ | Gemini key（fallback） |
| `XAI_API_KEY` | _空_ | Grok key（fallback） |
| `PERPLEXITY_API_KEY` | _空_ | Perplexity key（fallback） |
| `DASHSCOPE_API_KEY` | _空_ | Qwen key（fallback） |
| `DEEPSEEK_API_KEY` | _空_ | DeepSeek key（fallback） |
| `EMBEDDING_PROVIDER` | `openai` | 向量化用的 provider（暂未启用，留位） |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | embedding 模型 |
| `EMBEDDING_DIM` | `1536` | embedding 维度，**改完要重建 viewpoints/experts/events.embedding 列** |
| `LANGSMITH_API_KEY` | _空_ | 可选，开启 LangGraph tracing |
| `MAX_TOKENS_PER_RUN` | `2000000` | 单次报告 token 上限 |
| `MAX_PROVIDER_CALLS_PER_RUN` | `300` | 单次报告 LLM 调用上限 |
| `COST_CAP_USD_PER_RUN` | `10.0` | 单次报告成本上限 |
| `MAX_REFLECTION_ROUNDS` | `3` | (预留 v2) Critic 反思最多轮数 |
| `FRONTEND_URL` | `http://localhost:3000` | CORS 白名单 |

---

## 数据库连接位置

DB 连接 URL **集中在两个地方**，需要一起改：

```
backend/.env  →  DATABASE_URL  +  DATABASE_URL_SYNC
docker-compose.yml  →  postgres service 的 POSTGRES_USER/PASSWORD/DB
                      +  backend service 的 environment.DATABASE_URL(_SYNC)
```

具体格式（asyncpg + psycopg）：

| 用途 | 变量 | 例 |
|---|---|---|
| FastAPI 后端运行时（async） | `DATABASE_URL` | `postgresql+asyncpg://USER:PASS@HOST:PORT/DB` |
| Alembic / LangGraph PostgresSaver（sync） | `DATABASE_URL_SYNC` | `postgresql://USER:PASS@HOST:PORT/DB` |

**Docker 模式下** hostname 是容器名 `postgres`，**裸装模式下** hostname 是 `localhost`。两者已在 docker-compose.yml 内通过 environment override 自动适配，你只要改 `.env` 一个文件即可（裸装时改 hostname 为 localhost，Docker 时不动）。

✅ pgvector 扩展会在 `alembic upgrade head` 时自动 `CREATE EXTENSION IF NOT EXISTS vector;`。

如果想换数据库（如别的 host、远程 RDS、本地不同端口）：

```bash
# 编辑 backend/.env
DATABASE_URL=postgresql+asyncpg://USER:PASS@HOST:PORT/DB
DATABASE_URL_SYNC=postgresql://USER:PASS@HOST:PORT/DB

# 重新跑迁移
cd backend
alembic upgrade head
```

---

## 使用流程

1. 打开 <http://localhost:3000>
2. 进入 **Settings**，**至少配 1 家 provider 的 API key** 并点 _Test connection_
   - 推荐组合：Anthropic + Perplexity + 1 个中文模型（Qwen 或 DeepSeek）
   - 全部 7 家都开效果最好但成本最高
3. 进入 **Templates**，看下 4 个内置模板（可以编辑后保存新版本，is_builtin 不可删）
4. **+ New Report** → 填：
   - Title: `ICT 产业打卡观点总结`
   - Focus topics: `Token 经济, 黄仁勋, 斯坦福 2026 AI 报告, Pichai 十年复盘`
   - Time window: `30` 天
   - Providers: 多选已配 key 的（默认全选）
   - 选 Markdown / PPT outline 模板
5. 提交后跳到 `/reports/[id]` 实时看：
   - 中间：Markdown 预览（自动刷新）
   - 右边：Provider calls 列表（成功/失败 + token + cost）
6. 完成后顶部按钮：
   - **Download PDF** —— weasyprint 渲染的 PDF
   - **Show PPT outline JSON** —— 复制后喂给 Gamma / Tome / 自己的 ChatGPT 生 PPT
7. **Experts / Events** 页面查看自动沉淀下来的专家库与事件库。下次跑同领域报告时它们就是免费的高质量种子。

---

## 项目结构

```
backend/
├── alembic/                       # 迁移
├── alembic.ini
├── Dockerfile
├── pyproject.toml
├── .env.example
└── app/
    ├── main.py                    # FastAPI 入口（注册所有路由）
    ├── config.py                  # pydantic-settings
    ├── db/
    │   ├── models.py              # SQLModel 14 张表
    │   ├── session.py             # async engine
    │   └── types.py               # pgvector + JSONB + ARRAY 字段封装
    ├── schemas/
    │   ├── llm.py                 # Pydantic LLM 结构化输出 schema
    │   └── api.py                 # API request/response shapes
    ├── api/
    │   ├── reports.py             # POST 创建 + GET 列表/详情/markdown/outline/pdf
    │   ├── templates.py           # 模板 CRUD
    │   ├── settings.py            # provider credentials CRUD + test
    │   ├── runs.py                # agent_runs / provider_calls + SSE 流
    │   └── knowledge.py           # experts/events/sources/topics/viewpoints/stats
    ├── providers/                 # 7 家 LLM/搜索 adapter
    │   ├── base.py                # SearchProvider 抽象
    │   ├── credentials.py         # DB 优先 + .env fallback
    │   ├── registry.py            # 工厂
    │   ├── anthropic_provider.py
    │   ├── openai_provider.py
    │   ├── gemini_provider.py
    │   ├── grok_provider.py
    │   ├── perplexity_provider.py
    │   └── openai_compat_provider.py  # Qwen + DeepSeek 共享实现
    ├── agents/                    # LangGraph 状态机
    │   ├── state.py
    │   ├── graph.py               # 主图组装
    │   ├── runner.py              # 后台跑 graph + 落库
    │   └── nodes/                 # 8 个节点
    ├── render/
    │   ├── template_engine.py     # Jinja2
    │   ├── markdown_renderer.py
    │   ├── ppt_outline_renderer.py
    │   └── pdf_renderer.py        # weasyprint
    └── seeds/                     # 默认数据
        ├── default_templates.py   # 4 个内置模板
        ├── default_events.py      # 10 个 anchor
        └── runner.py              # 幂等播种

frontend/
├── package.json
├── next.config.mjs                # rewrites: /api/* → backend
├── tsconfig.json
├── tailwind.config.ts
├── lib/{api.ts, types.ts}
├── components/Nav.tsx
└── app/
    ├── layout.tsx
    ├── globals.css
    ├── page.tsx                   # Dashboard
    ├── reports/{page, new, [id]}.tsx
    ├── templates/{page, new, [id]}.tsx
    ├── settings/page.tsx          # API key 配置 + Test connection
    ├── experts/page.tsx
    └── events/page.tsx

docker-compose.yml
```

---

## Agent 工作流

LangGraph 主图（[agents/graph.py](backend/app/agents/graph.py)）：

```
START
  → Planner               拆解主题 → 子查询 (中英 / 多视角)
  → MultiSearch           7 家 provider × 多查询 并行 fan-out (asyncio.gather)
  → DedupMerger           按 URL + 文本相似度合并跨源命中
  → ExpertDiscoverer      双向挖人：事件→人 + 主题→大咖；含长尾人物（如刘烈宏类）
  → ViewpointExtractor    7 元组结构化抽取
  → ClusterAnalyzer       LLM 聚类标签：consensus/dissent/spotlight/insight
  → KnowledgeWriter       experts/events/sources/viewpoints 落库
  → ReportComposer        FinalAnalysis + Jinja 渲染 MD/JSON/PDF + 写文件路径回 DB
END
```

> v2 计划加入 Critic ↔ GapFiller 反思循环（state 字段已预留 `max_reflection_rounds`）。

每节点 LLM 调用都会写一行到 `provider_calls` 表（含 provider/model/tokens/cost/latency），UI 实时展示。

---

## 常见问题

**Q：跑报告时一直卡在 `running`？**

打开 <http://localhost:8000/docs> 看 `/api/runs/report/{id}/provider-calls`，或者前端右侧栏看具体卡在哪个 provider；多半是某个 key 没配 / 余额不足。

**Q：PDF 生成失败？**

weasyprint 需要系统字体。Docker 镜像已装 `fonts-noto-cjk`；本地裸装的话 macOS 自带 PingFang，Linux 需要 `apt install fonts-noto-cjk`。

**Q：怎么换 embedding provider？**

`.env` 里改 `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `EMBEDDING_DIM`。**改维度后必须重建表的 `embedding` 列**（drop column + add column with new dim）。

**Q：日志在哪看？**

后端：终端直接 stdout（uvicorn）；Docker：`docker compose logs -f backend`。
LangSmith 接入：`.env` 填 `LANGSMITH_API_KEY` 即可，每次 graph 跑完上 LangSmith 看 trace。

**Q：报告里专家没找到我期待的人怎么办？**

1. 检查启用了哪几家 provider —— 中文长尾人物主要靠 Qwen / DeepSeek / Perplexity
2. 把那个论坛 / 节目手动加到 `events` 表（暂无 UI，可用 `psql` 直接 `INSERT`，下个版本会加 UI）
3. 模板里调整 prompt：在 `report_templates.prompt_template` 里加约束（如「优先列出政府官员/学者声音」）

**Q：Critic 反思循环什么时候做？**

state schema 已预留 `max_reflection_rounds`；下个迭代会加 `critic` + `gap_filler` 两个节点 + 条件边到主图。当前版本已经能拿到完整端到端报告。

---

## 设计文档

详见 [`/Users/jzl19991121/.claude/plans/ai-ppt-ict-token-2026-google-ceo-token-shimmying-floyd.md`](../.claude/plans/ai-ppt-ict-token-2026-google-ceo-token-shimmying-floyd.md)。
