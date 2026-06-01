from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import httpx
import os
import json
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("monitoring-proxy")

app = FastAPI(title="InferencePack Monitoring Proxy")

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
ENABLE_LANGFUSE = os.environ.get("ENABLE_LANGFUSE", "false").lower() == "true"

langfuse = None
if ENABLE_LANGFUSE:
    try:
        from langfuse import Langfuse
        langfuse = Langfuse(
            public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
            host=os.environ.get("LANGFUSE_HOST", "http://localhost:3000"),
        )
        logger.info("LangFuse integration enabled")
    except Exception as e:
        logger.warning(f"Failed to initialize LangFuse: {e}")
        langfuse = None

http_client = httpx.AsyncClient(timeout=300.0)

@app.on_event("shutdown")
async def shutdown():
    await http_client.aclose()

@app.get("/health")
async def health():
    return {"status": "ok", "backend": BACKEND_URL, "langfuse": langfuse is not None}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def proxy(request: Request, path: str):
    target_url = f"{BACKEND_URL}/{path}"
    if request.query_params:
        target_url += f"?{request.query_params}"
    
    body = await request.body()
    headers = dict(request.headers)
    headers.pop("host", None)
    
    is_chat_completion = path == "v1/chat/completions" and request.method == "POST"
    is_completion = path == "v1/completions" and request.method == "POST"
    
    trace = None
    generation = None
    
    if langfuse and (is_chat_completion or is_completion):
        try:
            data = json.loads(body) if body else {}
            trace_name = data.get("model", "unknown-model")
            trace = langfuse.trace(name="inference-request", user_id=data.get("user", "anonymous"))
            generation = trace.generation(
                name=trace_name,
                model=trace_name,
                input=data.get("messages") if is_chat_completion else data.get("prompt"),
            )
        except Exception as e:
            logger.warning(f"LangFuse trace creation failed: {e}")
    
    try:
        response = await http_client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
        )
    except Exception as e:
        logger.error(f"Backend request failed: {e}")
        if generation:
            generation.end()
        if trace:
            trace.update(metadata={"error": str(e)})
        return Response(content=str(e), status_code=502)
    
    response_body = await response.aread()
    
    if langfuse and generation and response.status_code == 200:
        try:
            resp_data = json.loads(response_body)
            choices = resp_data.get("choices", [])
            if choices:
                output_content = choices[0].get("message", {}).get("content", "") if is_chat_completion else choices[0].get("text", "")
                generation.end(output=output_content)
            usage = resp_data.get("usage", {})
            if usage:
                generation.update(usage={
                    "input": usage.get("prompt_tokens", 0),
                    "output": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0),
                })
        except Exception as e:
            logger.warning(f"LangFuse generation update failed: {e}")
    
    return Response(
        content=response_body,
        status_code=response.status_code,
        headers=dict(response.headers),
    )
