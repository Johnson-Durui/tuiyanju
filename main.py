"""FastAPI entrypoint for TuiYanJu (推演局 · Dynamic Cognitive Orchestrator).

Compatible with `uvicorn main:app` and serves both `/api/*` endpoints and static frontend assets.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from tuiyanju import __version__
from tuiyanju.config import (
    AUDIENCE_MAP,
    BASE_DIR,
    DEFAULT_AGENT_NAMES,
    DEFAULT_VOICE_PROFILES,
    DEPTH_MAP,
    DOCS_DIR,
    MODEL_LABELS,
    MODULES_CATALOG,
    MODULES_MAP,
    PREFERRED_MODEL_ORDER,
    get_api_config,
    get_cors_origins,
    get_env_value,
    get_rate_limit_per_minute,
    has_api_credentials,
    normalize_base_url,
)
from tuiyanju.models import (
    AnalyzeRequest,
    agent_display_name,
    build_fallback_casting,
    compute_agent_max_tokens,
    compute_casting_max_tokens,
    compute_director_max_tokens,
    compute_max_tokens,
    compute_roundtable_max_tokens,
    extract_json_object,
    normalize_casting,
    normalize_depth_key,
    normalize_orchestration_mode,
    parse_agent_count,
    parse_or_fallback_casting,
    should_include_roundtable,
)
from tuiyanju.orchestrator import (
    build_sse_message,
    fetch_available_models,
    format_exception_message,
    sort_model_ids,
    stream_analysis,
    stream_multi_agent_analysis,
    stream_single_pass_analysis,
)
from tuiyanju.prompts import (
    build_agent_prompt,
    build_casting_prompt,
    build_director_prompt,
    build_isolated_agent_system_prompt,
    build_prompt_context,
    build_roundtable_prompt,
    build_runtime_prompt,
    build_system_prompt,
    load_file,
    render_prompt,
)
from tuiyanju.rate_limit import SlidingWindowRateLimiter, extract_client_ip

app = FastAPI(
    title="推演局 · Dynamic Cognitive Orchestrator",
    version=__version__,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

cors_origins = get_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_origins != ["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

rate_limiter = SlidingWindowRateLimiter(
    max_requests=get_rate_limit_per_minute(),
    window_seconds=60.0,
)

if DOCS_DIR.is_dir():
    app.mount("/docs", StaticFiles(directory=str(DOCS_DIR)), name="docs")


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
async def serve_index() -> FileResponse:
    index_path = BASE_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_path, media_type="text/html; charset=utf-8")


@app.get("/theme.css", include_in_schema=False)
async def serve_theme_css() -> FileResponse:
    css_path = BASE_DIR / "theme.css"
    if not css_path.is_file():
        raise HTTPException(status_code=404, detail="theme.css not found")
    return FileResponse(css_path, media_type="text/css; charset=utf-8")


@app.get("/export_utils.js", include_in_schema=False)
async def serve_export_utils() -> FileResponse:
    js_path = BASE_DIR / "export_utils.js"
    if not js_path.is_file():
        raise HTTPException(status_code=404, detail="export_utils.js not found")
    return FileResponse(js_path, media_type="application/javascript; charset=utf-8")


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest, request: Request) -> StreamingResponse:
    if not req.topic.strip():
        raise HTTPException(status_code=400, detail="话题不能为空")

    decision = rate_limiter.check(extract_client_ip(request))
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail=f"请求过于频繁，请在 {decision.retry_after} 秒后重试",
            headers={
                "Retry-After": str(decision.retry_after),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
            },
        )

    return StreamingResponse(
        stream_analysis(req, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": str(decision.remaining),
        },
    )


@app.get("/api/health")
async def health() -> dict[str, object]:
    configured = has_api_credentials()
    base_url = normalize_base_url(
        get_env_value(
            "OPENAI_BASE_URL",
            "BASE_URL",
            "OPENAI_API_BASE",
            "API_BASE_URL",
        )
    )
    return {
        "status": "ok",
        "version": __version__,
        "message": "推演局已就绪",
        "provider_mode": "openai-compatible-relay",
        "orchestrator_mode": "true-multi-agent",
        "supported_modes": ["multi_agent", "single_stream", "demo"],
        "default_mode": "multi_agent" if configured else "demo",
        "demo_available": True,
        "api_configured": configured,
        "base_url": base_url,
    }


@app.get("/api/models")
async def get_models() -> dict[str, object]:
    try:
        api_key, base_url = get_api_config()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(connect=15.0, read=30.0, write=15.0, pool=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            models = await fetch_available_models(client, base_url, headers)
        default_model = models[0]["id"] if models else "claude-opus-4-6-thinking"
        return {"models": models, "default_model": default_model}
    except Exception as exc:
        fallback_ids = sort_model_ids(list(MODEL_LABELS.keys()))
        return {
            "models": [
                {"id": model_id, "label": MODEL_LABELS.get(model_id, model_id)}
                for model_id in fallback_ids
            ],
            "default_model": "claude-opus-4-6-thinking",
            "warning": format_exception_message(exc),
        }


@app.get("/api/modules")
async def get_modules() -> dict[str, object]:
    return {"modules": list(MODULES_CATALOG)}


__all__ = [
    "AUDIENCE_MAP",
    "AnalyzeRequest",
    "BASE_DIR",
    "DEFAULT_AGENT_NAMES",
    "DEFAULT_VOICE_PROFILES",
    "DEPTH_MAP",
    "MODEL_LABELS",
    "MODULES_CATALOG",
    "MODULES_MAP",
    "PREFERRED_MODEL_ORDER",
    "agent_display_name",
    "app",
    "build_agent_prompt",
    "build_casting_prompt",
    "build_director_prompt",
    "build_fallback_casting",
    "build_isolated_agent_system_prompt",
    "build_prompt_context",
    "build_roundtable_prompt",
    "build_runtime_prompt",
    "build_sse_message",
    "build_system_prompt",
    "compute_agent_max_tokens",
    "compute_casting_max_tokens",
    "compute_director_max_tokens",
    "compute_max_tokens",
    "compute_roundtable_max_tokens",
    "extract_json_object",
    "load_file",
    "normalize_casting",
    "normalize_depth_key",
    "normalize_orchestration_mode",
    "parse_agent_count",
    "parse_or_fallback_casting",
    "rate_limiter",
    "render_prompt",
    "should_include_roundtable",
    "stream_analysis",
    "stream_multi_agent_analysis",
    "stream_single_pass_analysis",
]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
