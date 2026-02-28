# MyAgent — 智能中文文档排版工具

基于规则的中文 Word 文档排版工具，支持接入大模型 API，实现智能排版分析。

---

## 功能概述

用户上传 Word 文档后，系统按照既定规则进行排版并输出新文档。引入大模型模块后，支持三种排版模式，兼容纯规则与 AI 辅助分析两种工作流程。

---

## 智能 Agent 模式

本项目支持三种排版模式，通过环境变量 `LLM_MODE` 控制：

| 模式 | 说明 |
|---|---|
| `rule` | 纯规则模式（默认兜底，无需 API Key） |
| `llm` | 纯 LLM 模式（完全由大模型分析文档结构） |
| `hybrid` | 混合模式（LLM 主判断，置信度不足时规则兜底，**推荐**） |

### 环境变量配置

```bash
export LLM_API_KEY="your-api-key"
export LLM_BASE_URL="https://your-llm-endpoint/v1"
export LLM_MODEL="gpt-4o"         # 或任意兼容模型名
export LLM_TIMEOUT_S="60"
export LLM_MODE="hybrid"          # rule | llm | hybrid
```

| 环境变量 | 说明 | 默认值 |
|---|---|---|
| `LLM_API_KEY` | 大模型 API 密钥 | `""` |
| `LLM_BASE_URL` | API 基础 URL | `"https://api.openai.com/v1"` |
| `LLM_MODEL` | 使用的模型名称 | `"gpt-4o"` |
| `LLM_TIMEOUT_S` | 请求超时秒数 | `60` |
| `LLM_MODE` | 排版模式 `rule/llm/hybrid` | `"hybrid"` |

### 架构说明

```
用户上传 Word 文档
        │
        ▼
  mode_router.py（根据 LLM_MODE 路由）
   ├── rule 模式  ──────────────────────► 规则排版引擎（现有逻辑）
   ├── llm 模式   ── DocAnalyzer ──► LLMClient ──► 结构化 JSON ──► 排版引擎
   └── hybrid 模式
         ├── LLM 分析成功且置信度高 ──► LLM 结构 JSON ──► 排版引擎
         ├── LLM 置信度低的段落    ──► 规则兜底
         └── LLM 完全失败          ──► 完全回退到规则模式
```

---

## 目录结构

```
MyAgent/
├── agent/
│   ├── __init__.py
│   ├── doc_analyzer.py      # 文档结构分析 Agent（调用 LLM）
│   ├── llm_client.py        # LLM 接入与调用封装
│   ├── mode_router.py       # 三种模式路由逻辑
│   ├── prompt_templates.py  # Prompt 模板管理
│   ├── schema.py            # JSON 输出 Schema 定义（pydantic）
│   └── Structura_agent.py   # 文档 Agent 主入口
├── core/                    # 规则排版核心模块
├── service/                 # 服务层（format_service）
├── specs/                   # 排版规范 YAML 配置
├── config.py                # 环境变量配置读取
├── format_docx.py           # CLI 入口
└── requirements.txt
```

---

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 纯规则模式（无需 API Key）

```bash
python format_docx.py input.docx output.docx --label-mode rule
```

### 纯 LLM 模式

```bash
export LLM_API_KEY="your-api-key"
export LLM_MODE="llm"
python format_docx.py input.docx output.docx --label-mode llm
```

### 混合模式（推荐）

```bash
export LLM_API_KEY="your-api-key"
export LLM_MODE="hybrid"
python format_docx.py input.docx output.docx --label-mode hybrid
```

---

## 模块说明

### `config.py`

从环境变量读取所有大模型相关配置，集中管理，便于部署和切换。

### `agent/schema.py`

使用 `pydantic` 定义结构化输出 Schema：
- `ParagraphTag`：单段落结构标签（段落类型、置信度、推理说明等）
- `DocumentStructure`：整文档结构分析结果

### `agent/llm_client.py`

封装大模型 API 调用：
- 基于 `openai` SDK，兼容所有 OpenAI 接口规范的模型（含国产模型）
- 支持超时控制（`LLM_TIMEOUT_S`）
- 统一异常处理，失败时抛出 `LLMCallError`

### `agent/prompt_templates.py`

管理系统 Prompt 和用户 Prompt 模板：
- `SYSTEM_PROMPT`：告知模型角色与输出格式要求
- `build_user_prompt(paragraphs)`：根据段落列表动态构造用户 Prompt

### `agent/doc_analyzer.py`

文档分析器：提取 `.docx` 段落文本 → 构造 Prompt → 调用 LLM → 返回 `DocumentStructure`。

### `agent/mode_router.py`

模式路由器：根据 `LLM_MODE` 将请求路由到 `rule` / `llm` / `hybrid` 三种处理分支，`hybrid` 模式包含完整的规则兜底逻辑。
