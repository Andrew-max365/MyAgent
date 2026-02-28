from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

import api.server as server_module
from agent.Structura_agent import AgentArtifacts, AgentResult
from api.server import app
from config import LLM_MODE


@pytest.fixture()
def client():
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_format_docx_json_endpoint(client):
    sample = Path("tests/samples/sample.docx")
    with sample.open("rb") as f:
        resp = client.post(
            "/v1/agent/format",
            files={"file": ("sample.docx", f.read(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"label_mode": "rule", "spec_path": "specs/default.yaml"},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert "output_docx_base64" in payload
    assert "report" in payload
    assert payload["agent_result"]["status"] == "ok"


def test_format_docx_bundle_endpoint(client):
    sample = Path("tests/samples/sample.docx")
    with sample.open("rb") as f:
        resp = client.post(
            "/v1/agent/format/bundle",
            files={"file": ("sample.docx", f.read(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"label_mode": "rule", "spec_path": "specs/default.yaml"},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/zip")
    assert len(resp.content) > 0


def test_format_docx_json_endpoint_uses_config_default_label_mode(client, monkeypatch):
    captured = {}

    def _fake_run_doc_agent_bytes(input_bytes, spec_path, filename_hint, label_mode):
        captured["label_mode"] = label_mode
        return b"fake-docx", AgentResult(
            status="ok",
            task="docx_format_and_audit",
            goal="goal",
            steps=[],
            summary="summary",
            report={},
            artifacts=AgentArtifacts(output_docx_path=None, report_json_path=None),
        )

    monkeypatch.setattr(server_module, "run_doc_agent_bytes", _fake_run_doc_agent_bytes)

    sample = Path("tests/samples/sample.docx")
    with sample.open("rb") as f:
        resp = client.post(
            "/v1/agent/format",
            files={"file": ("sample.docx", f.read(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"spec_path": "specs/default.yaml"},
        )

    assert resp.status_code == 200
    assert captured["label_mode"] == LLM_MODE
