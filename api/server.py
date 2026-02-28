from __future__ import annotations

import base64
import io
import json
import secrets
import zipfile
from dataclasses import asdict
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from agent.Structura_agent import run_doc_agent_bytes
from config import LLM_MODE, SERVER_API_KEY

app = FastAPI(
    title="Structura DOCX Agent API",
    version="0.1.0",
    description="API-ready Word 中文排版 Agent：上传 docx，返回排版结果与可解释报告。",
)


def _verify_api_key(x_api_key: str = Header(default="")) -> None:
    """若 SERVER_API_KEY 已配置，则验证请求头中的 X-API-Key。"""
    if SERVER_API_KEY and not secrets.compare_digest(x_api_key, SERVER_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/agent/format", dependencies=[Depends(_verify_api_key)])
async def format_docx_json(
    file: UploadFile = File(..., description="待排版的 .docx 文件"),
    spec_path: str = Form("specs/default.yaml"),
    label_mode: Literal["rule", "llm", "hybrid"] = Form(LLM_MODE),
):
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are supported")

    input_bytes = await file.read()
    if not input_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        out_bytes, agent_res = run_doc_agent_bytes(
            input_bytes,
            spec_path=spec_path,
            filename_hint=file.filename,
            label_mode=label_mode,
        )
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"formatting failed: {e}") from e

    return JSONResponse(
        {
            "status": "ok",
            "filename": file.filename,
            "output_docx_base64": base64.b64encode(out_bytes).decode("utf-8"),
            "report": agent_res.report,
            "agent_result": asdict(agent_res),
        }
    )


@app.post("/v1/agent/format/bundle", dependencies=[Depends(_verify_api_key)])
async def format_docx_bundle(
    file: UploadFile = File(..., description="待排版的 .docx 文件"),
    spec_path: str = Form("specs/default.yaml"),
    label_mode: Literal["rule", "llm", "hybrid"] = Form(LLM_MODE),
):
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only .docx files are supported")

    input_bytes = await file.read()
    if not input_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        out_bytes, agent_res = run_doc_agent_bytes(
            input_bytes,
            spec_path=spec_path,
            filename_hint=file.filename,
            label_mode=label_mode,
        )
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"formatting failed: {e}") from e

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("output.docx", out_bytes)
        zf.writestr("report.json", json.dumps(agent_res.report, ensure_ascii=False, indent=2))
        zf.writestr("agent_result.json", json.dumps(asdict(agent_res), ensure_ascii=False, indent=2))

    payload.seek(0)
    return StreamingResponse(
        payload,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="structura_bundle.zip"'},
    )
