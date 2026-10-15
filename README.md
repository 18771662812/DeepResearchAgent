# DeepResearchAgent

一个从零实现的深度研究 Agent：输入一个问题，Agent 会拆解子问题，由多个研究员 Agent 并行检索、阅读原文，审查缺口后补充研究，最终生成一份带引用的研究报告。

- **后端**：Python · FastAPI · 手写 tool-use 循环与多 Agent 编排（不依赖 LangChain 等框架）· SSE 流式推送
- **LLM**：DeepSeek（`deepseek-flash`，OpenAI 兼容接口）
- **前端**：Vue 3 · Vite · TypeScript

## 架构

支持两种模式，每次请求可以单独选择：

**多 Agent 深度研究（默认）**

```
              用户问题
                 │
           ┌─────▼─────┐
           │  Planner  │  拆解为 ≤4 个相互独立的子问题（JSON 输出）
           └─────┬─────┘
       ┌─────────┼─────────┐        并行执行，信号量控制并发
  ┌────▼───┐ ┌───▼────┐ ┌──▼─────┐
  │Research│ │Research│ │Research│  各自运行独立的 tool-use 循环
  │  er R1 │ │  er R2 │ │  er R3 │  （web_search / fetch_url）
  └────┬───┘ └───┬────┘ └──┬─────┘  只交回 ≤600 字的研究笔记
       └─────────┼─────────┘
           ┌─────▼─────┐
           │ Reflector │  审查笔记：发现缺口 → 补充子问题，进入下一轮
           └─────┬─────┘  信息充分 → 进入撰写
           ┌─────▼─────┐
           │  Writer   │  只基于笔记撰写报告，引用编号全局统一
           └───────────┘
```

**单 Agent 快速研究**：一个 tool-use 循环边检索边写报告，调用次数少、速度快，同时作为评测基线。

**服务端整体结构**

```
┌──────────── Vue 前端 ────────────┐
│  POST /api/research  创建任务    │
│  GET  /api/research/{id}/events  │◄── SSE 实时事件流（断线可续传）
└───────────────┬──────────────────┘
┌───────────────▼─────────── FastAPI ─────────────────────────┐
│ TaskManager    后台运行任务，与 HTTP 连接解耦；事件按序保存    │
│ MultiAgent / SingleAgent                                    │
│   └─ run_tool_loop  手写循环：LLM ⇄ ToolRegistry             │
│        ├─ web_search  (ddgs / Tavily / 博查)                 │
│        └─ fetch_url   (正文提取 + SSRF 防护)                  │
│ SourceRegistry  全局来源编号，报告中的 [n] 由程序生成参考文献   │
└─────────────────────────────────────────────────────────────┘
```

## 实测数据

模型 `deepseek-flash`（reasoning_effort=low），搜索 `ddgs`，成本按 DeepSeek 高峰时段价格估算。

| 问题 | 模式 | 耗时 | LLM 调用 | 输入 / 输出 tokens | 报告 | 引用来源 | 上下文压缩 | 成本 |
|---|---|---|---|---|---|---|---|---|
| MCP 协议是什么？有哪些主流实现和应用场景？ | 单 Agent | 75s | 6 | 31.4K / 4.1K | 5.6K 字 | 32 | — | $0.008 |
| 同上 | 多 Agent | 112s | 18 | 64.0K / 15.6K | 7.2K 字 | 23 | 83.7K → 5.2K 字（-94%） | $0.030 |
| 2026 年中国新能源汽车出口情况、主要市场、代表企业和贸易壁垒 | 多 Agent（2 轮） | — | 39 | 110.2K / 18.2K | — | 44 | 55.5K → 6.9K 字（-88%） | $0.041 |

观察：
- **上下文隔离**：多 Agent 模式下 Writer 的输入只有约 2.9K tokens（单 Agent 最后一次调用要带上全部检索历史），研究员读到的原始网页被压缩了约 90%。
- **报告更深入**：同一问题，多 Agent 报告覆盖了 SDK 分级、云厂商支持、具体 CVE 等细节，并单独整理了"研究缺口与不确定之处"。
- **反思能自我纠错**：新能源汽车的例子中，首轮多个研究员因搜索服务失效拿不到数据，Reflector 识别出 5 个缺口并补充 2 个子问题，第二轮补齐了 1—9 月出口数据。
- 代价是调用次数和成本约为单 Agent 的 3~4 倍，后续评测会量化质量收益是否值得。

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
- `ddgs`（默认）：免 key 的元搜索，开箱即用，但较慢且经常无结果；需要代理时会自动读取 `HTTPS_PROXY`
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

## 评测

`backend/eval/` 是一套离线评测流水线，用来回答"多 Agent 多花的钱值不值"，也用来验证后续每次改动是变好还是变坏。

### 方法

| 维度 | 做法 |
|---|---|
| 题集 | 10 道自建题目，覆盖技术、行业、科学、政策；每题附 5~7 条**参考要点**（描述应覆盖的方面而非具体数字，避免答案过期） |
| 报告质量 | LLM-as-Judge 按全面性、深度、切题性、可读性打 1~10 分，并逐条判断参考要点 covered / partial / missing |
| 两两对比 | 同一问题的单 / 多 Agent 报告交给裁判比较，**交换 A/B 顺序各判一次**，两次结论不一致记为平局，抵消位置偏差 |
| 引用准确率 | 每篇报告随机抽 10 条带引用的陈述，让裁判对照 **Agent 当时实际读到的来源内容**判断 supported / partial / unsupported；同时统计引用了不存在编号的"编造引用" |
| 效率 | 耗时、LLM 调用次数、tokens、成本、搜索失败率 |

几个细节：
- **裁判用更强的 `deepseek-v4-pro`**，与被评测的 `deepseek-flash` 区分开，减轻自我偏好。
- **核查引用时只给相关片段**：来源正文最长 8000 字，直接截取前 3000 字会漏掉后文的证据。改为按重叠窗口切分、用字符二元组重合度挑选与陈述最相关的片段。在同一批 20 条陈述上，这一改动把测得的引用准确率从 65% / 70% 修正到 85% / 95%，原先的低分是评测方法本身的偏差。
- 研究在进程内直接调用 Agent（不走 HTTP），这样能拿到每个来源的完整内容；每条研究结果单独存盘，`--rejudge` 可以只重跑评判、不重跑研究。

### 运行

```bash
cd backend
uv run python -m eval.run                                  # 全部题目 × 单 / 多 Agent
uv run python -m eval.run --questions tech-mcp --modes multi
uv run python -m eval.run --rejudge eval/results/<目录>     # 复用研究结果，只重新评判
```

结果写入 `backend/eval/results/<时间戳>/`：`summary.md`（汇总报告）、`summary.json`、`runs/*.json`（每次研究的报告、来源、评分明细）。全量跑一次约 25 分钟、$1.5。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/research` | 创建研究任务，body：`{"query": "...", "mode": "multi" \| "single"}`，返回 `task_id` |
| GET | `/api/research` | 任务列表 |
| GET | `/api/research/{id}` | 任务详情（含报告和来源） |
| GET | `/api/research/{id}/events` | SSE 事件流，支持 `Last-Event-ID` 断点续传 |
| GET | `/api/health` | 健康检查 |

事件类型：`phase` `plan` `researcher_start` `researcher_done` `reflection` `status` `step` `thought` `tool_call` `tool_result` `report` `usage` `error` `done`。研究员产生的事件带有 `agent` 字段（如 `"R1"`）。

## 目录结构

```
backend/
  app/
    main.py                 # FastAPI 入口、生命周期、CORS
    config.py               # 配置（pydantic-settings，读取 .env）
    api/research.py         # REST + SSE 接口
    services/task_manager.py# 后台任务、事件存储与订阅
    agent/
      loop.py               # 手写 tool-use 循环（单 Agent 与研究员共用）
      multi_agent.py        # 多 Agent 编排：Planner / Researcher / Reflector / Writer
      single_agent.py       # 单 Agent 基线
      prompts.py            # 各角色提示词
      sources.py            # 来源登记与引用解析
      events.py             # 事件模型
      factory.py            # 按模式组装 Agent
    llm/
      client.py             # DeepSeek 客户端、token 用量统计
      structured.py         # JSON 输出 + Pydantic 校验 + 失败重试
    tools/
      base.py               # Tool 抽象 + ToolRegistry
      search.py             # 搜索 Provider（ddgs / Tavily / 博查）
      fetch.py              # 网页抓取与正文提取
  eval/
    datasets/questions.jsonl# 评测题集（问题 + 参考要点）
    run.py                  # 评测入口（命令行）
    runner.py               # 运行研究、收集指标、调度评判
    judges.py               # LLM 裁判：质量打分 / 引用核查 / 两两对比
    citations.py            # 陈述抽取、相关片段选取
    report.py               # 汇总统计与 Markdown 报告
  tests/                    # 单元测试 + 接口测试
frontend/
  src/
    App.vue                 # 布局、任务状态
    api/research.ts         # 接口与 SSE 订阅
    components/             # 输入框、研究计划面板、过程时间线、报告渲染
```

## 设计要点

- **手写 Agent 循环**：不用框架，完整掌握消息历史、工具调用、思考模式下 `reasoning_content` 回传等细节。
- **上下文隔离与压缩**：研究员在各自的对话中阅读原始网页，只把压缩后的笔记交给主流程，主流程的上下文不随检索量膨胀。
- **反思驱动的多轮研究**：Reflector 审查笔记中的缺口与矛盾，按需补充子问题，轮数与补充数量都有上限，防止无限循环。
- **结构化输出 + 降级**：Planner / Reflector 使用 JSON 输出并用 Pydantic 校验，不合法时把错误反馈给模型重试一次，仍失败则降级（直接研究原问题 / 视为信息充分）。
- **故障隔离**：单个研究员失败不会中断任务；工具错误转成文本交给模型自行修正。
- **引用防编造**：并行研究员共享同一个来源登记表，编号全局唯一；参考文献由程序根据 `[n]` 生成，链接一定真实存在。
- **任务与连接解耦**：刷新页面、断网重连不影响研究；`Last-Event-ID` 从断点继续推送。
- **SSRF 防护**：`fetch_url` 的 URL 由模型生成，禁止访问内网地址。

## Roadmap

- [x] **阶段 1**：单 Agent + 搜索/抓取工具 + SSE + 前端
- [x] **阶段 2**：Planner 拆解子问题 → 多个 Researcher 并行 → Reflector 查漏补缺 → Writer；子 Agent 结果压缩
- [ ] **阶段 3**：评测体系（自建题集 + LLM-as-Judge），对比单 / 多 Agent 的报告质量、引用准确率、成本与延迟
- [ ] **阶段 4**：可观测性（Langfuse / OpenTelemetry）、持久化（Postgres + Redis）、Docker Compose 部署
- [ ] 其他：Writer 输出 token 级流式、PDF 解析、搜索结果缓存、MCP 工具接入
