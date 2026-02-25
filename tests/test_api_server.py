from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from api.server import app


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
