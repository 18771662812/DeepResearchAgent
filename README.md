# DeepResearchAgent

一个从零实现的深度研究 Agent：输入一个问题，Agent 自主进行多轮网络检索、阅读原文，最终生成一份带引用的研究报告。

- **后端**：Python · FastAPI · 手写 tool-use 循环（不依赖 LangChain 等框架）· SSE 流式推送
- **LLM**：DeepSeek（`deepseek-flash`，OpenAI 兼容接口）
- **前端**：Vue 3 · Vite · TypeScript

## 架构

```
┌──────────── Vue 前端 ────────────┐
│  POST /api/research  创建任务    │
│  GET  /api/research/{id}/events  │◄── SSE 实时事件流（断线可续传）
└───────────────┬──────────────────┘
                │
┌───────────────▼─────────── FastAPI ────────────────────────┐
│ TaskManager   后台运行任务，与 HTTP 连接解耦；事件按序保存   │
│      │                                                     │
│      ▼                                                     │
│ ResearchAgent  手写循环：                                   │
│   LLM ──有工具调用──► ToolRegistry（并行执行、超时、错误兜底）│
│    ▲                    ├─ web_search  (ddgs/Tavily/博查)   │
│    └──── 工具结果 ◄──────┴─ fetch_url   (正文提取 + SSRF 防护)│
│   无工具调用 ⇒ 输出报告 ⇒ SourceRegistry 根据 [n] 生成参考来源 │
└────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 后端

需要 Python ≥ 3.11 和 [uv](https://docs.astral.sh/uv/)。

```bash
cd backend
cp .env.example .env      # 填写 DEEPSEEK_API_KEY
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

API 文档：http://localhost:8000/docs

搜索服务（`SEARCH_PROVIDER`）：
- `ddgs`（默认）：免 key 的元搜索，开箱即用，但较慢且偶尔无结果；需要代理时会自动读取 `HTTPS_PROXY`
- `tavily`：[Tavily](https://tavily.com)，每月有免费额度，速度和质量更好，**推荐**
- `bocha`：[博查](https://open.bochaai.com)，国内服务

### 2. 前端

需要 Node.js ≥ 20。

```bash
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173 。开发环境下 `/api` 请求由 Vite 代理到 `127.0.0.1:8000`。

### 3. 测试

```bash
cd backend
uv run pytest        # 使用假的 LLM 和工具，不消耗 API 额度
uv run ruff check .
```

## 实测数据（阶段 1）

| 问题 | 耗时 | LLM 调用 | 输入 / 输出 tokens | 缓存命中率 | 引用来源 |
|---|---|---|---|---|---|
| MCP 协议是什么？有哪些主流实现和应用场景？ | 75s | 6 | 31.4K / 4.1K | 67% | 32 |
| 对比 Rust 和 Go 在后端开发中的优劣 | — | 5 | 45.5K / 3.7K | 66% | 14 |

模型 `deepseek-flash`（reasoning_effort=low），搜索 `ddgs`。单次研究成本约 $0.01。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/research` | 创建研究任务，返回 `task_id` |
| GET | `/api/research` | 任务列表 |
| GET | `/api/research/{id}` | 任务详情（含报告和来源） |
| GET | `/api/research/{id}/events` | SSE 事件流，支持 `Last-Event-ID` 断点续传 |
| GET | `/api/health` | 健康检查 |

事件类型：`status` `step` `thought` `tool_call` `tool_result` `report` `usage` `error` `done`

## 目录结构

```
backend/
  app/
    main.py                 # FastAPI 入口、生命周期、CORS
    config.py               # 配置（pydantic-settings，读取 .env）
    api/research.py         # REST + SSE 接口
    services/task_manager.py# 后台任务、事件存储与订阅
    agent/
      research_agent.py     # 核心：手写 tool-use 循环
      prompts.py            # 提示词
      sources.py            # 来源登记与引用解析
      events.py             # 事件模型
      factory.py            # 组装 Agent
    llm/client.py           # DeepSeek 客户端、token 用量统计
    tools/
      base.py               # Tool 抽象 + ToolRegistry
      search.py             # 搜索 Provider（Tavily / 博查）
      fetch.py              # 网页抓取与正文提取
  tests/                    # 单元测试 + 接口测试
frontend/
  src/
    App.vue                 # 布局、任务状态
    api/research.ts         # 接口与 SSE 订阅
    components/             # 输入框、研究过程时间线、报告渲染
```

## 设计要点

- **手写 Agent 循环**：不用框架，完整掌握消息历史、工具调用、思考模式下 `reasoning_content` 回传等细节。
- **引用防编造**：每个检索到的 URL 由程序分配编号，模型只输出 `[n]`，参考来源由程序生成，链接一定真实存在。
- **工具错误不中断**：参数错误、超时、网络异常都转成文本返回给模型，由模型自行修正。
- **任务与连接解耦**：刷新页面、断网重连不影响研究；`Last-Event-ID` 从断点继续推送。
- **SSRF 防护**：`fetch_url` 的 URL 由模型生成，禁止访问内网地址。

## Roadmap

- [x] **阶段 1**：单 Agent + 搜索/抓取工具 + SSE + 前端
- [ ] **阶段 2**：Planner 拆解子问题 → 多个 Researcher 并行 → Reflector 查漏补缺；子 Agent 结果压缩
- [ ] **阶段 3**：评测体系（自建题集 + LLM-as-Judge），量化报告质量、引用准确率、成本与延迟
- [ ] **阶段 4**：可观测性（Langfuse / OpenTelemetry）、持久化（Postgres + Redis）、Docker Compose 部署
- [ ] 其他：LLM 输出 token 级流式、PDF 解析、搜索结果缓存、MCP 工具接入
