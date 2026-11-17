"""Web backend for the live boardroom: FastAPI + Server-Sent Events + one static page.

The browser never receives an API key: /api/status reports provider and model names only.
The founder's clicks arrive here and are the only way an approval record is ever created.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import gates
import guardrails
from llm import LLMClient
from orchestrator import MOCKED_PARTS, PHASES, Run
from panel import panel_mode

app = FastAPI(title="VentureBoard")
WEB = config.ROOT / "web"
RUNS: dict[str, Run] = {}
FOUNDERS: dict[str, "WebFounder"] = {}


class WebFounder:
    """Blocks the pipeline until the founder answers in the browser."""

    def __init__(self):
        self.run: Run | None = None
        self.pending: dict[str, queue.Queue] = {}

    def ask(self, request: dict) -> dict:
        request_id = uuid.uuid4().hex[:10]
        box: queue.Queue = queue.Queue(maxsize=1)
        self.pending[request_id] = box
        self.run.emit("founder_request", request_id=request_id, request=request)
        answer = box.get()                      # waits for the founder; there is no timeout and no default
        self.run.emit("founder_answered", request_id=request_id)
        return answer

    def answer(self, request_id: str, answer: dict) -> None:
        box = self.pending.pop(request_id, None)
        if box is None:
            raise KeyError(request_id)
        box.put(answer)


class Brief(BaseModel):
    idea: str = ""
    skills: str = ""
    budget: str = ""
    hours_per_week: str = ""
    target_market: str = ""
    values: str = ""


class Answer(BaseModel):
    request_id: str
    answer: dict


class Note(BaseModel):
    text: str


def _run(run_id: str) -> Run:
    if run_id not in RUNS:
        raise HTTPException(404, "run not found")
    return RUNS[run_id]


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/status")
def status():
    client = LLMClient()
    info = client.describe()
    local_ready = None
    if "ollama" in info["chain"]:
        try:
            base = client.cfg["providers"]["ollama"]["base_url"].rstrip("/")
            tags = httpx.get(base + "/api/tags", timeout=3.0).json().get("models", [])
            local_ready = any(m.get("name", "").startswith(client.cfg["ollama_model"]) for m in tags)
        except (httpx.HTTPError, ValueError):
            local_ready = False

    class _Probe:            # panel_mode() only needs .llm.primary
        llm = client
    return {"llm": info, "local_model": client.cfg["ollama_model"], "local_model_ready": local_ready,
            "panel_mode": panel_mode(_Probe), "thresholds": gates.thresholds(), "mocked": MOCKED_PARTS,
            "phases": PHASES}


@app.post("/api/check")
def check(note: Note):
    """Try a request against the rule pre-filter without starting a run."""
    result = guardrails.prefilter(note.text)
    return {"blocked": result.blocked, "kind": result.kind, "message": result.recommendation,
            "rules": [v.rule for v in result.violations]}


@app.post("/api/runs")
def start_run(brief: Brief):
    if not brief.idea.strip():
        raise HTTPException(400, "The brief needs a starting idea.")
    founder = WebFounder()
    run = Run(brief.model_dump(), founder)
    founder.run = run
    RUNS[run.id], FOUNDERS[run.id] = run, founder
    threading.Thread(target=run.execute, name=f"run-{run.id}", daemon=True).start()
    return {"run_id": run.id}


@app.get("/api/runs/{run_id}/events")
def events(run_id: str, since: int = 0):
    run = _run(run_id)

    def stream():
        i = since
        while True:
            while i < len(run.events):
                yield f"data: {json.dumps(run.events[i], default=str)}\n\n"
                i += 1
            if run.status in ("completed", "stop", "error") and i >= len(run.events):
                yield "event: end\ndata: {}\n\n"
                return
            time.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/runs/{run_id}/answer")
def answer(run_id: str, body: Answer):
    _run(run_id)
    try:
        FOUNDERS[run_id].answer(body.request_id, body.answer)
    except KeyError:
        raise HTTPException(409, "That request was already answered.")
    return {"ok": True}


@app.post("/api/runs/{run_id}/note")
def note(run_id: str, body: Note):
    return _run(run_id).add_note(body.text)


@app.get("/api/runs/{run_id}/log")
def log(run_id: str):
    return _run(run_id).log.read()


@app.get("/api/runs/{run_id}/files/{name}")
def file(run_id: str, name: str):
    run = _run(run_id)
    path = (run.out_dir / Path(name).name).resolve()
    if not path.is_file() or path.parent != run.out_dir.resolve():
        raise HTTPException(404, "file not found")
    media = "text/html" if path.suffix == ".html" else "text/plain; charset=utf-8"
    return FileResponse(path, media_type=media)


app.mount("/static", StaticFiles(directory=WEB), name="static")
