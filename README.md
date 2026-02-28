# MyAgent — 智能文档排版工具

基于规则与大模型的中文 Word 文档自动排版工具。用户上传 `.docx` 文档，系统按照既定规范进行排版并输出新文档，同时支持接入大模型 API 进行智能结构分析。

---

## 功能特性

- 自动识别文档中的标题层级、正文、列表、题注等段落类型
- 支持软回车拆段、空行清理、字体/间距/缩进等排版规范应用
- 输出可解释的 JSON 诊断报告
- **三种工作模式**：纯规则 / 纯大模型 / 混合（推荐）

---

## 智能 Agent 模式

### 工作模式对比

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `rule` | 纯规则模式，完全基于正则/样式规则识别文档结构 | 离线环境、无需 API Key |
| `llm` | 纯 LLM 模式，完全由大模型识别文档结构并输出标签 | 结构复杂、规则难以覆盖的文档 |
| `hybrid` | 混合模式：LLM 主判断 + 规则兜底（置信度 < 0.7 时回退规则，LLM 失败时全量回退） | **推荐生产使用** |

### 环境变量配置

在运行前设置以下环境变量（均有默认值，`rule` 模式下无需设置 API Key）：

| 环境变量 | 说明 | 默认值 |
|---|---|---|
| `LLM_API_KEY` | 大模型 API 密钥 | `""` |
| `LLM_BASE_URL` | API 基础 URL，支持国产兼容模型 | `"https://api.openai.com/v1"` |
| `LLM_MODEL` | 使用的模型名称 | `"gpt-4o"` |
| `LLM_TIMEOUT_S` | 请求超时秒数 | `60` |
| `LLM_MODE` | 排版模式 `rule/llm/hybrid` | `"hybrid"` |

**示例（Linux/macOS）：**

```bash
export LLM_API_KEY="sk-xxxxxxxx"
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-4o"
export LLM_MODE="hybrid"
```

**示例（Windows PowerShell）：**

```powershell
$env:LLM_API_KEY = "sk-xxxxxxxx"
$env:LLM_MODE = "hybrid"
```

---

## 架构说明

```
MyAgent/
├── config.py                # 从环境变量读取全局配置
├── agent/
│   ├── __init__.py
│   ├── schema.py            # pydantic 结构化输出 Schema
│   ├── llm_client.py        # LLM 接入与调用封装（openai SDK）
│   ├── prompt_templates.py  # Prompt 模板管理
│   ├── doc_analyzer.py      # 文档结构分析 Agent
│   ├── mode_router.py       # 三种模式路由逻辑
│   └── Structura_agent.py   # 顶层 Agent 入口
├── core/                    # 规则排版核心模块
│   ├── parser.py            # docx 解析 → Block 列表
│   ├── judge.py             # 规则标签（rule_based_labels）
│   ├── formatter.py         # 排版应用
│   ├── writer.py            # 输出保存
│   └── ...
├── service/
│   └── format_service.py    # 排版服务层（对接 core 与 agent）
├── api/                     # FastAPI 接口
├── ui/                      # Streamlit UI
├── specs/                   # 排版规范 YAML
└── requirements.txt
```

### 模块关系

```
ModeRouter（mode_router.py）
  ├── rule  →  core.judge.rule_based_labels（无 LLM 调用）
  ├── llm   →  DocAnalyzer → LLMClient → OpenAI API
  └── hybrid → DocAnalyzer（高置信度段落） + rule_based_labels（低置信度兜底）
```

---

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### CLI 使用

```bash
# 纯规则模式（默认）
python -m agent.Structura_agent input.docx output.docx --label-mode rule

# 混合模式（需设置 LLM_API_KEY）
export LLM_API_KEY="sk-xxxxxxxx"
python -m agent.Structura_agent input.docx output.docx --label-mode hybrid

# 纯 LLM 模式
python -m agent.Structura_agent input.docx output.docx --label-mode llm
```

### API 服务

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### Web UI

```bash
streamlit run ui/app.py
```

---

## 依赖说明

| 包 | 版本要求 | 用途 |
|---|---|---|
| `python-docx` | `>=1.1.0` | Word 文档读写 |
| `openai` | `>=1.0.0` | LLM API 调用 |
| `pydantic` | `>=2.0.0` | 结构化输出 Schema 定义与校验 |
| `PyYAML` | `==6.0.2` | 排版规范配置读取 |
| `fastapi` | `==0.115.0` | REST API 服务 |
| `streamlit` | `==1.39.0` | Web UI |
