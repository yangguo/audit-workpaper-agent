try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import argparse
import asyncio
import json
import logging
import os
import traceback
import uuid
from typing import Any, Dict, Optional, AsyncGenerator

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from api.upload import router as upload_router
from langchain_core.runnables import RunnableConfig

from review.runner import get_status as get_review_status
from review.artifact_view import build_artifact_view
from storage.findings_store import load_findings
from storage.review_artifact_store import ReviewArtifactStore
from utils.context import Context, request_context, new_context

_log_dir = os.path.join(os.getcwd(), "logs")
os.makedirs(_log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(_log_dir, "app.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 900

_frontend_origins_env = os.getenv("FRONTEND_ORIGINS")
if _frontend_origins_env is None:
    frontend_origins = ["http://localhost:3000"]
else:
    frontend_origins = [o.strip() for o in _frontend_origins_env.split(",") if o.strip()]
    if not frontend_origins:
        frontend_origins = ["http://localhost:3000"]

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(upload_router)


def _is_dev_env() -> bool:
    return os.getenv("APP_ENV") == "DEV"


class GraphService:
    def __init__(self):
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.task_results: Dict[str, Dict[str, Any]] = {}
        self._graph = None

    def _get_graph(self):
        if self._graph is not None:
            return self._graph
        from agents.agent import build_agent
        self._graph = build_agent()
        return self._graph

    @staticmethod
    def _sse_event(data: Any, event_id: Any = None) -> str:
        id_line = f"id: {event_id}\n" if event_id else ""
        return f"{id_line}event: message\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    async def run(self, payload: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
        run_id = ctx.run_id
        logger.info(f"Starting run with run_id: {run_id}")

        try:
            graph = self._get_graph()
            run_config: RunnableConfig = {"configurable": {"thread_id": run_id}}

            result = await graph.ainvoke(payload, config=run_config)
            logger.info(f"Run ainvoke completed, run_id: {run_id}, messages: {len(result.get('messages', []))}")
            return result

        except asyncio.CancelledError:
            logger.info(f"Run {run_id} was cancelled")
            return {"status": "cancelled", "run_id": run_id, "message": "Execution was cancelled"}
        except Exception as e:
            logger.error(f"Run {run_id} error: {e}\n{traceback.format_exc()}")
            return {"status": "error", "run_id": run_id, "message": str(e)}
        finally:
            self.running_tasks.pop(run_id, None)

    async def run_streamed(
        self,
        payload: Dict[str, Any],
        ctx: Context,
        on_messages=None,
    ) -> Dict[str, Any]:
        """Run the agent with streaming so intermediate tool messages are visible.

        Unlike `run` (which awaits `ainvoke` and only returns at completion),
        this iterates `graph.astream(stream_mode="updates")` and invokes
        `on_messages(accumulated_messages)` after each node emits messages —
        letting the caller surface tool-call info (e.g. the review_workpaper
        args) to the UI seconds in, long before the whole task finishes.

        Returns the same shape as `run`: `{"messages": [...]}` (or error dicts).

        Note: `run` returns the graph's final *windowed* state (the agent's
        reducer keeps the last 40 messages), while this accumulates *every*
        message emitted across the run. For a single review request (a handful
        of messages) the two are identical; they only diverge in a long
        multi-turn session that exceeds the window. The two consumers here
        (final-AI-text scan and `_extract_review_summary`) both take the *last*
        matching message, so they remain correct either way.
        """
        run_id = ctx.run_id
        logger.info(f"Starting streamed run with run_id: {run_id}")

        try:
            graph = self._get_graph()
            run_config: RunnableConfig = {"configurable": {"thread_id": run_id}}

            messages: list = []
            async for chunk in graph.astream(payload, config=run_config, stream_mode="updates"):
                if not isinstance(chunk, dict):
                    continue
                for update in chunk.values():
                    if not isinstance(update, dict):
                        continue
                    node_msgs = update.get("messages") or []
                    for m in node_msgs:
                        messages.append(m)
                    if node_msgs and on_messages is not None:
                        try:
                            on_messages(messages)
                        except Exception:
                            logger.exception(f"on_messages callback error, run_id: {run_id}")

            logger.info(f"Streamed run completed, run_id: {run_id}, messages: {len(messages)}")
            return {"messages": messages}

        except asyncio.CancelledError:
            logger.info(f"Streamed run {run_id} was cancelled")
            return {"status": "cancelled", "run_id": run_id, "message": "Execution was cancelled"}
        except Exception as e:
            logger.error(f"Streamed run {run_id} error: {e}\n{traceback.format_exc()}")
            return {"status": "error", "run_id": run_id, "message": str(e)}
        finally:
            self.running_tasks.pop(run_id, None)

    async def stream_sse(
        self, payload: Dict[str, Any], ctx: Context
    ) -> AsyncGenerator[str, None]:
        run_id = ctx.run_id
        logger.info(f"Starting stream with run_id: {run_id}")
        graph = self._get_graph()
        run_config: RunnableConfig = {"configurable": {"thread_id": run_id}}

        try:
            result = await graph.ainvoke(payload, config=run_config)
            logger.info(f"Stream ainvoke completed, run_id: {run_id}")
            messages = result.get("messages", [])
            logger.info(f"Stream got {len(messages)} messages")
            for msg in messages:
                if msg.type == "ai" and hasattr(msg, "content") and msg.content:
                    text = msg.content
                    if isinstance(text, str) and text.strip():
                        logger.info(f"Stream yielding AI message, length: {len(text)}")
                        yield self._sse_event({
                            "choices": [{"delta": {"content": text}}]
                        })
            logger.info(f"Stream finished yielding, run_id: {run_id}")
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield self._sse_event({
                "error": {"message": str(e), "type": "stream_error"}
            })
        finally:
            self.running_tasks.pop(run_id, None)

    def cancel_run(self, run_id: str) -> Dict[str, Any]:
        logger.info(f"Attempting to cancel run_id: {run_id}")

        if run_id in self.running_tasks:
            task = self.running_tasks[run_id]
            if not task.done():
                task.cancel()
                logger.info(f"Cancellation requested for run_id: {run_id}")
                return {
                    "status": "success",
                    "run_id": run_id,
                    "message": "Cancellation signal sent",
                }
            else:
                return {
                    "status": "already_completed",
                    "run_id": run_id,
                    "message": "Task has already completed",
                }
        else:
            return {
                "status": "not_found",
                "run_id": run_id,
                "message": "No active task found with this run_id",
            }


service = GraphService()

HEADER_X_RUN_ID = "x-run-id"


@app.post("/run")
async def http_run(request: Request) -> Dict[str, Any]:
    ctx = new_context(method="run")
    upstream_run_id = request.headers.get(HEADER_X_RUN_ID)
    if upstream_run_id:
        ctx.run_id = upstream_run_id
    run_id = ctx.run_id
    request_context.set(ctx)

    try:
        payload = await request.json()
        logger.info(f"Received request for /run: run_id={run_id}")

        task = asyncio.create_task(service.run(payload, ctx))
        service.running_tasks[run_id] = task

        try:
            result = await asyncio.wait_for(task, timeout=float(TIMEOUT_SECONDS))
        except asyncio.TimeoutError:
            logger.error(f"Run execution timeout after {TIMEOUT_SECONDS}s for run_id: {run_id}")
            task.cancel()
            return {
                "status": "timeout",
                "run_id": run_id,
                "message": f"Execution timeout: exceeded {TIMEOUT_SECONDS} seconds",
            }

        if not result:
            result = {}
        if isinstance(result, dict):
            result["run_id"] = run_id
        return result

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except asyncio.CancelledError:
        return {"status": "cancelled", "run_id": run_id, "message": "Execution was cancelled"}
    except Exception as e:
        logger.error(f"Unexpected error in http_run: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


def _register_task(run_id: str, task: asyncio.Task):
    service.running_tasks[run_id] = task


@app.post("/stream_run")
async def http_stream_run(request: Request):
    ctx = new_context(method="stream_run")
    upstream_run_id = request.headers.get(HEADER_X_RUN_ID)
    if upstream_run_id:
        ctx.run_id = upstream_run_id
    request_context.set(ctx)

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format")

    run_id = ctx.run_id
    logger.info(f"Received request for /stream_run: run_id={run_id}")

    async def stream_generator():
        try:
            async for event in service.stream_sse(payload, ctx):
                yield event
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            yield service._sse_event({
                "status": "cancelled", "run_id": run_id, "message": "Execution was cancelled"
            })
        except Exception as e:
            logger.error(f"Stream error: {e}\n{traceback.format_exc()}")
            yield service._sse_event({
                "status": "error", "run_id": run_id, "message": str(e)
            })

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@app.post("/cancel/{run_id}")
async def http_cancel(run_id: str, request: Request):
    ctx = new_context(method="cancel")
    request_context.set(ctx)
    logger.info(f"Received cancel request for run_id: {run_id}")
    return service.cancel_run(run_id)


@app.get("/v1/chat/completions/result/{task_id}")
async def get_chat_result(task_id: str):
    result = service.task_results.get(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if result["status"] == "processing":
        return result
    if result["status"] == "error":
        return {"status": "error", "error": result.get("error", "Unknown error")}
    return {
        "status": "completed",
        "choices": [{"message": {"role": "assistant", "content": result["content"]}}],
        "review_id": result.get("review_id"),
        "review_summary": result.get("review_summary"),
    }


def _tc_name(tc: Any) -> str:
    """Normalize a tool-call's name across dict / ToolCall-object forms."""
    if isinstance(tc, dict):
        return tc.get("name", "") or ""
    return getattr(tc, "name", "") or ""


def _tc_args(tc: Any) -> Dict[str, Any]:
    if isinstance(tc, dict):
        return tc.get("args", {}) or {}
    return getattr(tc, "args", {}) or {}


def _extract_tool_call_info(messages) -> Optional[Dict[str, Any]]:
    """Extract review_workpaper call info (input args + return value) from messages.

    Scans the full message list: AIMessage.tool_calls carries the input args
    (file_path / sheets / ...); the ToolMessage carries the JSON return value
    (review_id / status / ...). Returns None if no review_workpaper call is found.
    """
    args: Optional[Dict[str, Any]] = None
    return_value: Dict[str, Any] = {}
    for m in messages or []:
        mtype = getattr(m, "type", "")
        if mtype == "ai":
            for tc in getattr(m, "tool_calls", None) or []:
                if _tc_name(tc) == "review_workpaper":
                    args = _tc_args(tc)
        elif mtype == "tool" and getattr(m, "name", "") == "review_workpaper":
            content = getattr(m, "content", "")
            if isinstance(content, str):
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        return_value = data
                except Exception:
                    pass
    if args is None and not return_value:
        return None
    return {"args": args or {}, "return_value": return_value}


def _build_understood_requirement(info: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministically build the 'understood review requirement' view model.

    Pure function over the tool-call args + return value — no LLM, so the
    displayed summary is always consistent with the actual parameters the
    agent used (the very thing the user wants to sanity-check).
    """
    args = info.get("args", {}) or {}
    rv = info.get("return_value", {}) or {}

    sheets_raw = str(args.get("sheets") or "").strip()
    scope = sheets_raw if sheets_raw else "全部 Sheet"

    workpaper = os.path.basename(str(args.get("file_path") or "")) or "（未指定）"
    checkpoints = os.path.basename(str(args.get("checkpoints_path") or "")) or None
    attachments_dir = os.path.basename(str(args.get("attachments_dir") or "")) or None
    legacy_attachments_preview = os.path.basename(
        str(args.get("attachments_preview_path") or "")
    ) or None

    extras: list = []
    if checkpoints:
        extras.append(f"检查要点：{checkpoints}")
    if attachments_dir:
        extras.append(f"附件目录：{attachments_dir}")
    elif legacy_attachments_preview:
        extras.append(f"附件预览：{legacy_attachments_preview}")
    extra_text = "，".join(extras)

    summary = f"将审阅 {scope}（底稿：{workpaper}"
    if extra_text:
        summary += f"，含{extra_text}"
    summary += "）"

    return {
        "review_id": rv.get("review_id"),
        "status": rv.get("status"),
        "scope": scope,
        "sheets_raw": sheets_raw,
        "workpaper": workpaper,
        "checkpoints": checkpoints,
        "attachments_dir": attachments_dir,
        "attachments_preview": legacy_attachments_preview,
        "summary": summary,
    }


def _extract_review_summary(messages) -> Optional[Dict[str, Any]]:
    """Find the latest review_workpaper call and return its understood-requirement dict.

    Backward-compatible entry point: returns a dict that always carries
    `review_id`/`status` (consumed by the existing completion path) plus the
    richer understood-requirement fields used by the UI card.
    """
    info = _extract_tool_call_info(messages)
    if info is None:
        return None
    return _build_understood_requirement(info)


@app.get("/findings/{review_id}")
async def get_findings(review_id: str):
    payload = load_findings(review_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="findings not found")
    return payload


@app.get("/review/{review_id}/status")
async def review_status(review_id: str):
    """Lightweight status for a background review (polled by the frontend)."""
    st = get_review_status(review_id)
    if st is not None:
        return st
    # registry cleared (e.g. restart) but findings file may exist from a prior run
    payload = load_findings(review_id)
    if payload is not None:
        return {
            "review_id": review_id,
            "status": "completed",
            "source": payload.get("source"),
            "stats": payload.get("stats"),
        }
    raise HTTPException(status_code=404, detail="review not found")


@app.get("/review/{review_id}/artifact")
async def review_artifact(review_id: str):
    """Return a bounded, read-only view of the Evidence-First artifacts."""
    store = ReviewArtifactStore()
    try:
        manifest = store.load_manifest(review_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail="review artifact not found")
        return build_artifact_view(
            review_id=review_id,
            manifest=manifest,
            evidence=store.load_json(review_id, "evidence.json"),
            plan=store.load_json(review_id, "review-plan.json"),
            policy_findings=store.load_json(review_id, "policy-findings.json"),
            v2_findings=store.load_json(review_id, "v2-findings.json"),
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="review artifact not found")


@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Service is running"}


@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    ctx = new_context(method="openai_chat")
    request_context.set(ctx)
    run_id = ctx.run_id
    logger.info(f"Received request for /v1/chat/completions: run_id={run_id}")

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format")

    messages = payload.get("messages", [])
    session_id = payload.get("session_id", run_id)
    stream = payload.get("stream", False)

    user_text = ""
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                user_text = content
            elif isinstance(content, list):
                user_text = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
                )

    agent_payload = {"messages": [{"role": "user", "content": user_text}]}

    if stream:
        ctx.run_id = session_id

        async def sse_generator():
            async for event in service.stream_sse(agent_payload, ctx):
                yield event
            logger.info(f"SSE generator complete, sending [DONE], session: {ctx.run_id}")
            yield "data: [DONE]\n\n"

        return StreamingResponse(sse_generator(), media_type="text/event-stream")
    else:
        task_id = uuid.uuid4().hex
        ctx.run_id = task_id
        service.task_results[task_id] = {"status": "processing"}

        async def run_agent_background():
            last_sig: Optional[tuple] = None

            def on_messages(msgs):
                """Surface the understood review requirement as soon as the
                review_workpaper tool call is seen — seconds in, not minutes.

                The signature includes review_id/status (not just the summary
                string) so the enrichment from the ToolMessage (review_id,
                status="running") fires as a second update after the initial
                AIMessage(tool_calls) — letting the frontend start review-status
                polling before the whole agent task completes.
                """
                nonlocal last_sig
                understood = _extract_review_summary(msgs)
                if understood is None:
                    return
                sig = (
                    understood.get("summary", ""),
                    understood.get("review_id"),
                    understood.get("status"),
                )
                if sig == last_sig:
                    return
                last_sig = sig
                service.task_results[task_id] = {
                    "status": "processing",
                    "review_summary": understood,
                }
                logger.info(f"Task {task_id} understood requirement: {understood.get('summary')}")

            try:
                result = await service.run_streamed(agent_payload, ctx, on_messages=on_messages)
                ai_text = ""
                msgs = result.get("messages", [])
                for m in reversed(msgs):
                    if hasattr(m, "content") and getattr(m, "type", "") == "ai":
                        ai_text = m.content
                        break
                review_summary = _extract_review_summary(msgs)
                service.task_results[task_id] = {
                    "status": "completed",
                    "content": ai_text or str(result),
                    "review_id": review_summary.get("review_id") if review_summary else None,
                    "review_summary": review_summary,
                }
                logger.info(f"Task {task_id} completed, ai_text length: {len(ai_text)}")
            except Exception as e:
                service.task_results[task_id] = {
                    "status": "error",
                    "error": str(e),
                }
                logger.error(f"Task {task_id} error: {e}")

        asyncio.create_task(run_agent_background())
        logger.info(f"Task {task_id} started in background")
        return {"task_id": task_id, "status": "processing"}


def parse_args():
    parser = argparse.ArgumentParser(description="Start FastAPI server")
    parser.add_argument("-m", type=str, default="http", help="Run mode: http, flow, node")
    parser.add_argument("-n", type=str, default="", help="Node ID for single node run")
    parser.add_argument("-p", type=int, default=5000, help="HTTP server port")
    parser.add_argument("-i", type=str, default="", help="Input JSON string for flow/node mode")
    return parser.parse_args()


def start_http_server(port):
    reload = _is_dev_env()
    logger.info(f"Start HTTP Server, Port: {port}, Workers: 1, Reload: {reload}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=reload, workers=1)


if __name__ == "__main__":
    args = parse_args()
    if args.m == "http":
        start_http_server(args.p)
    elif args.m == "flow":
        payload = json.loads(args.i) if args.i else {"text": "你好"}
        ctx = new_context(method="flow")
        result = asyncio.run(service.run(payload, ctx))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.m == "node" and args.n:
        print(json.dumps({"error": "node_run not supported without coze workflow"}, ensure_ascii=False))
