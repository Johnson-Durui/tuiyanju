"""Orchestrator tests: True Concurrent Multi-Agent Isolation, Single-Stream, Fallback, Tokens, Cancellation."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from tuiyanju.models import AnalyzeRequest, compute_max_tokens, parse_or_fallback_casting
from tuiyanju.orchestrator import stream_analysis


def _sse_stream_response(chunks: list[str], finish_reason: str = "stop") -> httpx.Response:
    lines: list[str] = []
    for text in chunks:
        pkt = {"choices": [{"delta": {"content": text}, "finish_reason": None}]}
        lines.append(f"data: {json.dumps(pkt, ensure_ascii=False)}\n\n")
    end_pkt = {"choices": [{"delta": {}, "finish_reason": finish_reason}]}
    lines.append(f"data: {json.dumps(end_pkt, ensure_ascii=False)}\n\n")
    lines.append("data: [DONE]\n\n")
    body = "".join(lines).encode("utf-8")
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def _mock_casting_json() -> str:
    return json.dumps(
        {
            "issue_type": "科技冲击型",
            "topic_deconstruction": {
                "surface_conflict": "AI 是提效还是替代",
                "real_dispute": "谁拿走红利、谁承担转型成本",
                "key_variables": ["标准化程度", "签字责任", "缓冲期"],
                "loud_but_minor": "极端贩卖焦虑帖",
                "silent_but_powerful": "财务预算审批表",
            },
            "conflict_axes": ["效率红利 vs 议价权", "短期成本 vs 长期梯队", "有牌者 vs 承受者"],
            "agents": [
                {
                    "id": "agent_1",
                    "display_name": "苏晴",
                    "alias": "焦虑执行岗",
                    "age": "27岁",
                    "identity": "广告文案策划",
                    "core_interest": "保住岗位单价",
                    "main_fear": "沦为AI改稿机器",
                    "info_type": "日常改稿返工率",
                    "dimensions": ["直接承受", "职业迁移"],
                    "blind_spot": "低估客户沟通门槛",
                    "why_selected": "一线直接冲击样本",
                },
                {
                    "id": "agent_2",
                    "display_name": "郑总",
                    "alias": "成本核算老板",
                    "age": "42岁",
                    "identity": "中型营销机构创始人",
                    "core_interest": "守住毛利率",
                    "main_fear": "人力成本压垮现金流",
                    "info_type": "公司季度损益表",
                    "dimensions": ["预算开关", "经营风险"],
                    "blind_spot": "忽视新人断代",
                    "why_selected": "握有用人预算开关",
                },
                {
                    "id": "agent_3",
                    "display_name": "何工",
                    "alias": "落地工程师",
                    "age": "32岁",
                    "identity": "企业工作流实施顾问",
                    "core_interest": "交付验收回款",
                    "main_fear": "客户流程混乱甩锅技术",
                    "info_type": "真实POC准确率",
                    "dimensions": ["技术边界", "实施摩擦"],
                    "blind_spot": "轻视组织惯性",
                    "why_selected": "掌握真实技术边界",
                },
                {
                    "id": "agent_4",
                    "display_name": "林律师",
                    "alias": "合规把关人",
                    "age": "44岁",
                    "identity": "知识产权与劳动法顾问",
                    "core_interest": "责任链条可追溯",
                    "main_fear": "版权或用工合规事故",
                    "info_type": "纠纷判例与监管口径",
                    "dimensions": ["制度约束", "签字责任"],
                    "blind_spot": "偏保守防御",
                    "why_selected": "补齐制度合规边界",
                },
            ],
        },
        ensure_ascii=False,
    )


def test_dynamic_max_tokens_scaling():
    quick = compute_max_tokens(AnalyzeRequest(topic="测试", depth="quick"))
    standard = compute_max_tokens(AnalyzeRequest(topic="测试", depth="standard"))
    pro = compute_max_tokens(AnalyzeRequest(topic="测试", depth="pro"))
    flagship = compute_max_tokens(
        AnalyzeRequest(
            topic="测试",
            depth="flagship",
            active_modules=["winners", "timeline", "signal", "action", "monitor", "appendix"],
            agent_count="8",
        )
    )

    assert quick < standard < pro < flagship
    assert 12000 <= flagship <= 16000


def test_resilient_casting_fallback_on_malformed_json():
    req = AnalyzeRequest(topic="新能源汽车价格战会持续多久", agent_count="5")
    casting, used_fallback = parse_or_fallback_casting("抱歉，我无法返回JSON：{broken...", req)
    assert used_fallback is True
    assert len(casting["agents"]) == 5
    assert "新能源汽车价格战会持续多久" in casting["topic_deconstruction"]["surface_conflict"]


async def test_true_multi_agent_concurrent_context_isolation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-unit-test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://mock.relay.local/v1")

    recorded_agent_payloads: dict[str, str] = {}
    in_flight = 0
    max_in_flight = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, max_in_flight
        body = json.loads(request.content.decode("utf-8"))
        user_msg = body["messages"][-1]["content"]

        # Stage 1: Casting (non-streaming)
        if not body.get("stream"):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": _mock_casting_json()}, "finish_reason": "stop"}]},
            )

        # Stage 3: Roundtable
        if "【圆桌激辩】" in user_msg:
            return _sse_stream_response(["# 圆桌激辩\n\n## 苏晴\n我不同意郑总只算短期账。"])

        # Stage 4: Director
        if "# 局长整合报告" in user_msg:
            return _sse_stream_response(
                [
                    "# 话题解构\n表面争工具，实际争议价权。\n\n",
                    "# 局长整合报告\n### A. 表层冲突\n争论激烈。\n### H. 立体真相\n不是替代全部人，而是重划议价权。\n\n",
                    "# 行动建议\n建议一：面向一线员工先提效。\n\n# 事实 / 推断 / 情绪分层\n- **事实层**：工具普及\n- **推断层**：分化加剧\n- **情绪层**：焦虑放大",
                ]
            )

        # Stage 2: Isolated Darkroom Agent
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.04)
        in_flight -= 1

        for name in ("苏晴", "郑总", "何工", "林律师"):
            if f"你的主显示名：{name}" in user_msg:
                recorded_agent_payloads[name] = json.dumps(body["messages"], ensure_ascii=False)
                return _sse_stream_response([f"我是{name}，", "我只从自己的真实利益出发看这件事。"])

        raise AssertionError(f"Unexpected prompt: {user_msg[:120]}")

    transport = httpx.MockTransport(handler)
    req = AnalyzeRequest(
        topic="AI 会替代大部分白领工作吗？",
        depth="pro",
        orchestration_mode="multi_agent",
    )

    events: list[dict[str, Any]] = []
    async for raw_frame in stream_analysis(req, None, transport=transport):
        for line in raw_frame.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    # 1. Verify all 4 agents ran concurrently (max_in_flight >= 2)
    assert len(recorded_agent_payloads) == 4
    assert max_in_flight >= 2, f"Expected concurrent execution, got max_in_flight={max_in_flight}"

    # 2. Verify strict physical context isolation: each agent NEVER sees any other agent's name or identity!
    all_names = {"苏晴", "郑总", "何工", "林律师"}
    for agent_name, full_messages_blob in recorded_agent_payloads.items():
        other_names = all_names - {agent_name}
        for other in other_names:
            assert other not in full_messages_blob, f"Context leak: {agent_name} prompt contained {other}"

    # 3. Verify complete 4-stage SSE event lifecycle
    types = [e["type"] for e in events]
    assert "casting" in types
    assert types.count("agent_done") == 4
    assert "roundtable_done" in types
    assert "director_done" in types
    assert types[-1] == "done"


async def test_single_stream_mode_and_disconnect_cancellation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-unit-test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://mock.relay.local/v1")

    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _sse_stream_response(["# 话题解构\n单流第一段\n\n", "# 局长整合报告\n单流结论"])

    transport = httpx.MockTransport(handler)
    req = AnalyzeRequest(topic="年轻人该不该买房", orchestration_mode="single_stream")

    events = []
    async for raw_frame in stream_analysis(req, None, transport=transport):
        for line in raw_frame.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    assert call_count == 1
    assert any(e["type"] == "chunk" for e in events)
    assert events[-1]["type"] == "done"

    # Now verify disconnect cancellation stops generation early
    class DisconnectingRequest:
        def __init__(self) -> None:
            self.checks = 0

        async def is_disconnected(self) -> bool:
            self.checks += 1
            return self.checks >= 2

    disc_events = []
    fake_request = DisconnectingRequest()
    async for raw_frame in stream_analysis(req, fake_request, transport=transport):  # type: ignore[arg-type]
        for line in raw_frame.splitlines():
            if line.startswith("data: "):
                disc_events.append(json.loads(line[6:]))

    assert all(e["type"] != "done" for e in disc_events)


async def test_sse_heartbeat_emission_and_stage1_fallback_in_pipeline(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-unit-test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://mock.relay.local/v1")

    class SlowByteStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0.05)
            pkt = {"choices": [{"delta": {"content": "# 话题解构\n测试心跳与兜底\n\n# 局长整合报告\n### H. 立体真相\n结论清晰。"}, "finish_reason": "stop"}]}
            yield f"data: {json.dumps(pkt, ensure_ascii=False)}\n\ndata: [DONE]\n\n".encode("utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        # Stage 1 returns non-JSON text to trigger resilient casting fallback
        if not body.get("stream"):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "非标准选角文本输出"}, "finish_reason": "stop"}]},
            )
        user_msg = body["messages"][-1]["content"]
        if "# 局长整合报告" in user_msg:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=SlowByteStream(),
            )
        return _sse_stream_response(["我是暗房角色，这是我的独立判断。"])

    transport = httpx.MockTransport(handler)
    req = AnalyzeRequest(topic="延迟退休对年轻人的影响", depth="quick", orchestration_mode="multi_agent")

    events = []
    async for raw_frame in stream_analysis(req, None, transport=transport, heartbeat_interval=0.015):
        for line in raw_frame.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    event_types = [e["type"] for e in events]
    assert "casting" in event_types
    assert "heartbeat" in event_types
    assert any("兜底" in str(e.get("label", "")) for e in events if e["type"] == "status")
    assert event_types[-1] == "done"
