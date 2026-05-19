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
from typing import Any, Dict, Optional, AsyncGenerator

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from api.upload import router as upload_router
from langchain_core.runnables import RunnableConfig

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
    return os.getenv("COZE_PROJECT_ENV") == "DEV"


class GraphService:
    def __init__(self):
        self.running_tasks: Dict[str, asyncio.Task] = {}
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

            return await graph.ainvoke(payload, config=run_config)

        except asyncio.CancelledError:
            logger.info(f"Run {run_id} was cancelled")
            return {"status": "cancelled", "run_id": run_id, "message": "Execution was cancelled"}
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
            messages = result.get("messages", [])
            for msg in messages:
                if msg.type == "ai" and hasattr(msg, "content") and msg.content:
                    text = msg.content
                    if isinstance(text, str) and text.strip():
                        yield self._sse_event({
                            "choices": [{"delta": {"content": text}}]
                        })
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
            yield "data: [DONE]\n\n"

        return StreamingResponse(sse_generator(), media_type="text/event-stream")
    else:
        ctx.run_id = session_id
        result = await service.run(agent_payload, ctx)
        # Extract the last AI message text from agent result
        ai_text = ""
        msgs = result.get("messages", [])
        for m in reversed(msgs):
            if hasattr(m, "content") and getattr(m, "type", "") == "ai":
                ai_text = m.content
                break
        return {
            "choices": [{"message": {"role": "assistant", "content": ai_text or str(result)}}]
        }


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
