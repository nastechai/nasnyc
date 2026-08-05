"""
NasTech Sync Web Dashboard — FastAPI server.

Serves:
  GET  /          → dashboard (HTML)
  GET  /api/status → sync status JSON
  GET  /api/rules  → branding rules JSON
  GET  /api/history → recent sync history JSON
  POST /api/sync   → trigger a sync
  POST /api/ask    → ask the brain (streaming SSE)
  GET  /api/brain  → brain provider status
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import markdown2
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from .scheduler import NasTechScheduler

logger = logging.getLogger("nastech_sync.webapp")

STATIC_DIR = Path(__file__).parent.parent / "webapp" / "static"


def create_app(scheduler: "NasTechScheduler") -> FastAPI:
    app = FastAPI(title="NasTech Sync Dashboard", version="1.0.0")

    # Mount static files if directory exists
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        html_path = STATIC_DIR / "index.html"
        if html_path.exists():
            return HTMLResponse(html_path.read_text())
        return HTMLResponse("<h1>NasTech Sync Dashboard</h1><p>static/index.html not found</p>")

    # ------------------------------------------------------------------
    # API routes
    # ------------------------------------------------------------------

    @app.get("/api/status")
    async def api_status():
        try:
            status = scheduler.syncer.status()
            history = scheduler.get_sync_history()
            return JSONResponse({
                **status,
                "uptime_seconds": scheduler.uptime_seconds(),
                "next_sync_in": scheduler.next_sync_in_seconds(),
                "sync_interval_minutes": scheduler.interval_minutes,
                "recent_syncs": history[-10:],
            })
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @app.get("/api/rules")
    async def api_rules():
        rules = [
            {"find": r.find, "replace": r.replace, "case_sensitive": r.case_sensitive}
            for r in scheduler.config.branding_rules
        ]
        return JSONResponse({"rules": rules, "count": len(rules)})

    @app.get("/api/history")
    async def api_history():
        return JSONResponse({"history": scheduler.get_sync_history()})

    @app.post("/api/sync")
    async def api_sync(request: Request):
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        dry_run = body.get("dry_run", False)
        full = body.get("full", False)

        async def _run():
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: scheduler.syncer.run(dry_run=dry_run, force_full=full),
            )
            scheduler.record_sync(result)
            return result

        asyncio.create_task(_run())
        return JSONResponse({
            "started": True,
            "dry_run": dry_run,
            "message": "Sync started. Check /api/status for progress.",
        })

    @app.get("/api/brain")
    async def api_brain():
        statuses = scheduler.brain.provider_status()
        return JSONResponse({
            "providers": statuses,
            "any_available": any(statuses.values()),
        })

    @app.post("/api/ask")
    async def api_ask(request: Request):
        body = await request.json()
        question = body.get("question", "").strip()
        context = body.get("context", "")
        stream = body.get("stream", True)

        if not question:
            return JSONResponse({"error": "question required"}, status_code=400)

        if stream:
            async def event_generator():
                async for chunk in scheduler.brain.stream_ask(question, context):
                    data = json.dumps({"chunk": chunk})
                    yield f"data: {data}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            answer = await scheduler.brain.ask(question, context)
            return JSONResponse({"answer": answer})

    @app.post("/api/render-markdown")
    async def api_render_markdown(request: Request):
        body = await request.json()
        md_text = body.get("text", "")
        html = markdown2.markdown(
            md_text,
            extras=["fenced-code-blocks", "tables", "strike", "task_list", "footnotes"],
        )
        return JSONResponse({"html": html})

    @app.get("/api/brand-preview")
    async def api_brand_preview(text: str = ""):
        if not text:
            return JSONResponse({"error": "text param required"}, status_code=400)
        branded = scheduler.brander.brand_text(text)
        changes = scheduler.brander.describe_changes(text, branded)
        return JSONResponse({
            "original": text,
            "branded": branded,
            "changed": branded != text,
            "changes": changes,
        })

    @app.get("/api/upstream-info")
    async def api_upstream_info():
        """Return info about NousResearch/hermes-agent learned from codebase."""
        return JSONResponse({
            "upstream": {
                "org": "NousResearch",
                "repo": "hermes-agent",
                "url": "https://github.com/NousResearch/hermes-agent",
                "description": (
                    "Hermes is NousResearch's family of open-weight language models "
                    "fine-tuned for function calling, reasoning, and agentic workflows. "
                    "Built on Mistral and Llama base models."
                ),
                "model_family": "Hermes 2 / Hermes 3",
                "specialties": [
                    "Function calling & tool use",
                    "Structured output (JSON mode)",
                    "Multi-turn reasoning",
                    "Agent frameworks (ReAct, OpenAI tools format)",
                ],
            },
            "downstream": {
                "org": "nastechai",
                "repo": "NasTech-Agent",
                "url": "https://github.com/nastechai/NasTech-Agent",
                "description": (
                    "NasTech-Agent is the NasTech Research branded version of the "
                    "hermes-agent, always kept in sync and extended with NasTech features."
                ),
            },
        })

    return app
