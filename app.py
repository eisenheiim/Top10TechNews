"""Vercel / local FastAPI entrypoint for Top10TechNews."""

from __future__ import annotations

import traceback

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from pipeline import run
from web import load_payload, render_html, save_payload

app = FastAPI(title="Top10TechNews")


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(render_html(load_payload()))


@app.get("/api/payload")
def api_payload() -> dict:
    return load_payload()


@app.post("/refresh", response_class=HTMLResponse)
def refresh() -> HTMLResponse:
    error = ""
    try:
        payload = run(save=True)
        save_payload(payload)
    except Exception:
        error = traceback.format_exc()
        payload = load_payload()
    return HTMLResponse(render_html(payload, error=error))
