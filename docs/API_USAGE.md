# Structura Agent API 使用说明

## 启动

```bash
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

## 健康检查

```bash
curl http://127.0.0.1:8000/health
```

## 1) JSON 返回（含 base64 文档 + report）

```bash
curl -X POST "http://127.0.0.1:8000/v1/agent/format" \
  -F "file=@tests/samples/sample.docx" \
  -F "label_mode=rule" \
  -F "spec_path=specs/default.yaml"
```

返回字段：
- `output_docx_base64`：排版后文档
- `report`：排版诊断报告
- `agent_result`：Agent 执行摘要（steps/summary/artifacts）

## 2) Bundle 下载（output.docx + report.json + agent_result.json）

```bash
curl -X POST "http://127.0.0.1:8000/v1/agent/format/bundle" \
  -F "file=@tests/samples/sample.docx" \
  -F "label_mode=hybrid" \
  -o structura_bundle.zip
```

## LLM 模式环境变量

- `LLM_API_KEY`（必填）
- `LLM_BASE_URL`（可选，默认 `https://api.openai.com/v1`）
- `LLM_MODEL`（可选，默认 `gpt-4o-mini`）
- `LLM_TIMEOUT_S`（可选，默认 `45`）
