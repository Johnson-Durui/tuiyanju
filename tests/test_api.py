"""API, static serving, rate limiter, and demo streaming tests via ASGI."""

from __future__ import annotations

import json

import httpx

import main
from tuiyanju.rate_limit import SlidingWindowRateLimiter


def _parse_sse_events(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


async def test_health_and_metadata_endpoints(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/api/health")
        assert res.status_code == 200
        payload = res.json()
        assert payload["status"] == "ok"
        assert payload["demo_available"] is True
        assert payload["api_configured"] is False
        assert payload["default_mode"] == "demo"
        assert set(payload["supported_modes"]) == {"multi_agent", "single_stream", "demo"}

        mods_res = await client.get("/api/modules")
        assert mods_res.status_code == 200
        assert len(mods_res.json()["modules"]) == 6

        models_res = await client.get("/api/models")
        assert models_res.status_code == 200
        assert len(models_res.json()["models"]) >= 5


async def test_static_frontend_and_docs_served():
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        index_res = await client.get("/")
        assert index_res.status_code == 200
        assert "推演局 · Dynamic Cognitive Orchestrator" in index_res.text
        assert "真·多Agent并发隔离" in index_res.text

        css_res = await client.get("/theme.css")
        assert css_res.status_code == 200
        assert "--bg-primary" in css_res.text

        js_res = await client.get("/export_utils.js")
        assert js_res.status_code == 200
        assert "TuYanJuExportUtils" in js_res.text

        demo_pdf = await client.get("/docs/demo/github-smartest-report.pdf")
        assert demo_pdf.status_code == 200
        assert len(demo_pdf.content) > 1000


async def test_analyze_rejects_empty_topic():
    main.rate_limiter.reset()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.post("/api/analyze", json={"topic": "   "})
        assert res.status_code == 400
        assert "话题不能为空" in res.json()["detail"]


async def test_analyze_offline_demo_and_auto_fallback_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    main.rate_limiter.reset()

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.post(
            "/api/analyze",
            json={
                "topic": "AI 会替代大部分白领岗位吗？",
                "depth": "pro",
                "active_modules": ["winners", "monitor"],
                "orchestration_mode": "multi_agent",
            },
        )
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse_events(res.text)
        event_types = [e["type"] for e in events]

        assert "mode_resolved" in event_types
        resolved = next(e for e in events if e["type"] == "mode_resolved")
        assert resolved["mode"] == "demo"
        assert resolved["auto_fallback"] is True

        assert "casting" in event_types
        assert "agent_start" in event_types
        assert "agent_chunk" in event_types
        assert "agent_done" in event_types
        assert "roundtable_start" in event_types
        assert "roundtable_chunk" in event_types
        assert "roundtable_done" in event_types
        assert "director_start" in event_types
        assert "director_chunk" in event_types
        assert "director_done" in event_types
        assert event_types[-1] == "done"


async def test_sliding_window_rate_limiter_unit_and_endpoint():
    now = [100.0]
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60.0, clock=lambda: now[0])

    assert limiter.check("1.2.3.4").allowed is True
    assert limiter.check("1.2.3.4").allowed is True
    third = limiter.check("1.2.3.4")
    assert third.allowed is True
    assert third.remaining == 0

    fourth = limiter.check("1.2.3.4")
    assert fourth.allowed is False
    assert fourth.retry_after == 60

    # Other IP unaffected
    assert limiter.check("5.6.7.8").allowed is True

    # Advance past window -> allowed again
    now[0] = 161.0
    assert limiter.check("1.2.3.4").allowed is True

    # Endpoint integration test for HTTP 429
    original_limiter = main.rate_limiter
    main.rate_limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60.0)
    try:
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            payload = {"topic": "测试限流", "depth": "quick", "orchestration_mode": "demo"}
            assert (await client.post("/api/analyze", json=payload)).status_code == 200
            assert (await client.post("/api/analyze", json=payload)).status_code == 200
            blocked = await client.post("/api/analyze", json=payload)
            assert blocked.status_code == 429
            assert "Retry-After" in blocked.headers
    finally:
        main.rate_limiter = original_limiter
        main.rate_limiter.reset()
