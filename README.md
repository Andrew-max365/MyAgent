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
│   ├── default.yaml         # 通用默认模板
│   ├── academic.yaml        # 中文学术论文模板
│   ├── gov.yaml             # 政府公文模板（GB/T 9704）
│   └── contract.yaml        # 合同/协议模板
├── config.py                # 环境变量配置读取
├── format_docx.py           # CLI 入口
└── requirements.txt
```

---

## 专项模板库

通过 `--spec` 参数选择文档类型对应的排版规范，满足差异化语义样式需求：

| 模板文件 | 适用场景 | 特点 |
|---|---|---|
| `specs/default.yaml` | 通用文档 | 宋体/TNR，小四正文，摘要斜体 |
| `specs/academic.yaml` | 期刊/学位论文 | 五号正文，GB/T 7714 参考文献悬挂缩进 |
| `specs/gov.yaml` | 党政机关公文 | 仿宋_GB2312 四号，黑体标题，符合 GB/T 9704 |
| `specs/contract.yaml` | 合同/协议 | 宋体小四，条款标题黑体，签字落款专项样式 |

```bash
# 使用政府公文模板
python format_docx.py input.docx output.docx --spec specs/gov.yaml

# 使用学术论文模板 + hybrid 标注
python format_docx.py input.docx output.docx --spec specs/academic.yaml --label-mode hybrid
```

所有模板均支持完整的语义角色专项样式，包括 `abstract`、`keyword`、`reference`、`footer`、`list_item`，不再统一压扁为 `body`。

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

---

## 可量化基准（Quantifiable Benchmarks）

> 以下为当前测试集基准数据，用于衡量系统稳定性与可靠性。
> 测试平台：Python 3.11，python-docx 1.x，标准 x86 笔记本（8 核 16 GB）。

### 规则模式（rule）

| 指标 | 设计目标值 |
|---|---|
| 标题识别准确率（GB/T 编号格式） | ≥ 95% |
| 正文/空段分类准确率 | ≥ 98% |
| 单文档处理耗时 P50 / P95 | < 0.5 s / < 1.2 s（≤ 200 段） |
| 处理失败率（异常抛出） | < 0.1% |

### 混合模式（hybrid，GPT-4o）

| 指标 | 设计目标值 |
|---|---|
| 段落语义标签整体准确率 | ≥ 90%（含 abstract / keyword / reference / footer） |
| LLM 完全失败时规则兜底成功率 | 100% |
| 单文档端到端耗时 P50 / P95 | < 5 s / < 12 s（≤ 200 段，含 LLM 调用） |

### 格式输出质量

| 指标 | 设计目标值 |
|---|---|
| 空段压缩正确率（不误删跨容器） | 100% |
| 软回车拆段正确率 | 100% |
| 标签-格式映射覆盖率（无漏格角色） | 100%（h1/h2/h3/caption/body/abstract/keyword/reference/footer/list_item） |

> **说明**：上表为**设计目标值**，用于衡量系统稳定性与可靠性。
> 评测方法：在自有语料集上运行排版后，人工抽查 20% 段落，对照 spec 定义的字号/缩进/加粗/斜体进行对比。
> 若需在 CI 中自动收集覆盖率，运行 `python -m pytest tests/ -q` 并查看 `report.json` 中的 `labels.coverage` 与 `labels.consistency` 字段。
