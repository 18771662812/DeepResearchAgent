import json

from fastapi.testclient import TestClient

from app.main import app
from app.services.task_manager import TaskManager
from tests.test_task_manager import StepAgent


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if not line.startswith(":")]
        fields = dict(line.split(": ", 1) for line in lines)
        if "data" in fields:
            events.append((fields.get("id", ""), json.loads(fields["data"])))
    return events


def test_create_and_stream_research():
    with TestClient(app) as client:
        app.state.task_manager = TaskManager(StepAgent)

        resp = client.post("/api/research", json={"query": "测试问题"})
        assert resp.status_code == 201
        task_id = resp.json()["task_id"]

        with client.stream("GET", f"/api/research/{task_id}/events") as stream:
            body = "".join(stream.iter_text())
        events = parse_sse(body)
        assert [e[1]["type"] for e in events][-1] == "done"
        assert [e[0] for e in events] == [str(i) for i in range(len(events))]

        # 带 Last-Event-ID 重连，只收到之后的事件
        with client.stream(
            "GET", f"/api/research/{task_id}/events", headers={"Last-Event-ID": "3"}
        ) as stream:
            resumed = parse_sse("".join(stream.iter_text()))
        assert resumed[0][0] == "4"

        detail = client.get(f"/api/research/{task_id}").json()
        assert detail["status"] == "completed" and detail["report"] == "ok"
        assert client.get("/api/research").json()[0]["id"] == task_id


def test_unknown_task_returns_404():
    with TestClient(app) as client:
        assert client.get("/api/research/nope/events").status_code == 404


def test_validation():
    with TestClient(app) as client:
        assert client.post("/api/research", json={"query": ""}).status_code == 422
