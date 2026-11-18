"""Async SSE Orchestrator supporting Multi-Agent Isolated, Single-Stream, and Offline Demo modes."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import httpx
from fastapi import Request

from .config import (
    MODEL_LABELS,
    PREFERRED_MODEL_ORDER,
    get_api_config,
    get_max_concurrent_agents,
    has_api_credentials,
)
from .demo import stream_demo_multi_agent, stream_demo_single_stream
from .models import (
    AnalyzeRequest,
    agent_display_name,
    compute_agent_max_tokens,
    compute_casting_max_tokens,
    compute_director_max_tokens,
    compute_max_tokens,
    compute_roundtable_max_tokens,
    normalize_orchestration_mode,
    parse_or_fallback_casting,
    should_include_roundtable,
)
from .prompts import (
    build_agent_prompt,
    build_casting_prompt,
    build_director_prompt,
    build_isolated_agent_system_prompt,
    build_roundtable_prompt,
    build_system_prompt,
)


def build_sse_message(event_type: str, **payload: Any) -> str:
    data = {"type": event_type, **payload}
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def extract_message_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("中转站返回了空响应")

    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, str) and content.strip():
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        text = "".join(parts).strip()
        if text:
            return text

    raise RuntimeError("中转站返回格式异常，未找到可读文本内容")


def extract_finish_reason(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    return str(choices[0].get("finish_reason") or "").strip()


def should_retry_error(exc: Exception) -> bool:
    if isinstance(
        exc,
        (httpx.ConnectError, httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError),
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 429, 500, 502, 503, 504, 520, 521, 522, 524}
    return False


def extract_error_message(response: httpx.Response) -> str:
    try:
        raw_bytes = response.content
        message = raw_bytes.decode("utf-8", errors="replace") if raw_bytes else ""
    except Exception:
        message = ""
    try:
        data = json.loads(message) if message else {}
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            if isinstance(err, dict):
                return str(err.get("message") or message)
            return str(err)
    except Exception:
        pass
    return message or f"HTTP {response.status_code}"


def format_exception_message(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        detail = extract_error_message(exc.response).strip()
        return detail or f"上游返回 HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.ReadTimeout):
        return "中转站响应超时，请稍后重试或切换更快的模型"
    if isinstance(exc, httpx.ConnectError):
        return "连接中转站失败，请检查 Base URL 或网络连通性"
    message = str(exc).strip()
    if message:
        return message
    return exc.__class__.__name__ or "未知错误"


def sort_model_ids(model_ids: list[str]) -> list[str]:
    unique_ids: list[str] = []
    seen: set[str] = set()
    for model_id in model_ids:
        clean = str(model_id or "").strip()
        if clean and clean not in seen:
            unique_ids.append(clean)
            seen.add(clean)

    preferred = [model_id for model_id in PREFERRED_MODEL_ORDER if model_id in seen]
    remaining = sorted([model_id for model_id in unique_ids if model_id not in set(preferred)])
    return preferred + remaining


async def fetch_available_models(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
) -> list[dict[str, str]]:
    response = await client.get(f"{base_url}/models", headers=headers)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else []
    sorted_ids = sort_model_ids(
        [item.get("id") for item in data if isinstance(item, dict) and item.get("id")]
    )
    return [{"id": model_id, "label": MODEL_LABELS.get(model_id, model_id)} for model_id in sorted_ids]


async def request_text_completion(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    retries: int = 2,
) -> str:
    current_payload = dict(payload)
    for attempt in range(1, retries + 1):
        try:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=current_payload,
            )
            response.raise_for_status()
            body = response.json()
            if isinstance(body, dict) and body.get("error"):
                error = body["error"]
                if isinstance(error, dict):
                    raise RuntimeError(error.get("message") or "中转站返回了错误")
                raise RuntimeError("中转站返回了错误")
            if extract_finish_reason(body) == "length":
                previous_max_tokens = int(current_payload.get("max_tokens") or 0)
                if attempt < retries and previous_max_tokens:
                    current_payload["max_tokens"] = min(
                        max(previous_max_tokens + 1200, int(previous_max_tokens * 1.5)),
                        8000,
                    )
                    await asyncio.sleep(0.4 * attempt)
                    continue
                raise RuntimeError("结构化输出被截断，请增大 max_tokens 或压缩字段长度")
            return extract_message_text(body)
        except Exception as exc:
            if attempt < retries and should_retry_error(exc):
                await asyncio.sleep(0.5 * attempt)
                continue
            raise
    raise RuntimeError("请求未返回有效结果")


async def stream_text_completion(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    heartbeat_interval: float = 15.0,
) -> AsyncIterator[dict[str, Any]]:
    async with client.stream(
        "POST",
        f"{base_url}/chat/completions",
        headers=headers,
        json=payload,
    ) as response:
        if response.status_code >= 400:
            await response.aread()
            response.raise_for_status()

        line_iter = response.aiter_lines()
        next_line_task: asyncio.Task[str] | None = None
        try:
            while True:
                if next_line_task is None:
                    next_line_task = asyncio.create_task(line_iter.__anext__())
                done_set, _ = await asyncio.wait({next_line_task}, timeout=heartbeat_interval)
                if not done_set:
                    yield {"type": "heartbeat"}
                    continue

                finished_task = next_line_task
                next_line_task = None
                try:
                    raw_line = finished_task.result()
                except StopAsyncIteration:
                    break

                if not raw_line:
                    continue

                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue

                event_data = line[5:].strip()
                if event_data == "[DONE]":
                    break

                try:
                    packet = json.loads(event_data)
                except json.JSONDecodeError:
                    continue

                if isinstance(packet, dict) and packet.get("error"):
                    error = packet["error"]
                    if isinstance(error, dict):
                        raise RuntimeError(error.get("message") or "中转站返回了错误")
                    raise RuntimeError("中转站返回了错误")

                choices = packet.get("choices") or []
                if not choices:
                    continue

                delta = choices[0].get("delta") or {}
                reasoning_content = delta.get("reasoning_content")
                content = delta.get("content")
                finish_reason = choices[0].get("finish_reason")

                if reasoning_content:
                    yield {"type": "reasoning"}
                if content:
                    yield {"type": "content", "content": content}
                if finish_reason:
                    yield {"type": "finish", "finish_reason": finish_reason}
        finally:
            if next_line_task is not None and not next_line_task.done():
                next_line_task.cancel()
                await asyncio.gather(next_line_task, return_exceptions=True)


async def run_isolated_agent_stream(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    req: AnalyzeRequest,
    casting: dict[str, Any],
    agent: dict[str, Any],
    queue: asyncio.Queue[dict[str, Any]],
    semaphore: asyncio.Semaphore,
    *,
    heartbeat_interval: float = 15.0,
) -> dict[str, Any]:
    """Execute one Agent in a strictly isolated context window (zero cross-agent leakage)."""
    await queue.put({"type": "agent_start", "agent": agent})
    prompt = build_agent_prompt(req, casting, agent)
    isolated_system_prompt = build_isolated_agent_system_prompt()
    payload: dict[str, Any] = {
        "model": req.model,
        "messages": [
            {"role": "system", "content": isolated_system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": compute_agent_max_tokens(req),
        "stream": True,
    }

    async with semaphore:
        await queue.put(
            {
                "type": "agent_status",
                "agent_id": agent["id"],
                "label": "已进入独立暗房，正在组织第一人称独白",
            }
        )
        reasoning_announced = False
        monologue_parts: list[str] = []
        current_payload = dict(payload)

        for continuation_round in range(3):
            finish_reason = ""
            needs_resume = False
            for attempt in range(1, 3):
                received_content = False
                try:
                    async for event in stream_text_completion(
                        client,
                        base_url,
                        headers,
                        current_payload,
                        heartbeat_interval=heartbeat_interval,
                    ):
                        if event["type"] == "heartbeat":
                            await queue.put({"type": "heartbeat"})
                            continue
                        if event["type"] == "reasoning" and not reasoning_announced:
                            reasoning_announced = True
                            await queue.put(
                                {
                                    "type": "agent_status",
                                    "agent_id": agent["id"],
                                    "label": "正在暗房中深度推演利益与风险",
                                }
                            )
                        if event["type"] == "content":
                            received_content = True
                            monologue_parts.append(event["content"])
                            await queue.put(
                                {
                                    "type": "agent_chunk",
                                    "agent_id": agent["id"],
                                    "content": event["content"],
                                }
                            )
                        if event["type"] == "finish":
                            finish_reason = event.get("finish_reason") or ""
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if attempt < 2 and should_retry_error(exc) and not received_content:
                        await queue.put(
                            {
                                "type": "agent_status",
                                "agent_id": agent["id"],
                                "label": f"上游波动，正在重试（第 {attempt + 1} 次）",
                            }
                        )
                        await asyncio.sleep(0.5 * attempt)
                        continue
                    if should_retry_error(exc) and (received_content or monologue_parts):
                        needs_resume = True
                        break
                    await queue.put(
                        {
                            "type": "agent_error",
                            "agent_id": agent["id"],
                            "content": f"{agent_display_name(agent)} 推演失败：{format_exception_message(exc)}",
                        }
                    )
                    raise

            if finish_reason != "length" and not needs_resume:
                break
            if continuation_round >= 2:
                break

            current_payload = {
                "model": req.model,
                "messages": [
                    {"role": "system", "content": isolated_system_prompt},
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": "".join(monologue_parts)},
                    {
                        "role": "user",
                        "content": "请从刚才中断的地方继续说下去。不要重复已经说过的句子，保持第一人称和同样的说话习惯，把剩下还没说完的部分补完。",
                    },
                ],
                "max_tokens": max(1200, min(compute_agent_max_tokens(req), 4000)),
                "stream": True,
            }

        monologue = "".join(monologue_parts).strip()
        if not monologue:
            await queue.put(
                {
                    "type": "agent_error",
                    "agent_id": agent["id"],
                    "content": f"{agent_display_name(agent)} 没有返回有效独白",
                }
            )
            raise RuntimeError(f"{agent_display_name(agent)} 没有返回有效独白")

        await queue.put({"type": "agent_done", "agent_id": agent["id"]})
        return {**agent, "monologue": monologue}


async def _is_disconnected(request: Request | None) -> bool:
    if request is None:
        return False
    return bool(await request.is_disconnected())


async def stream_multi_agent_analysis(
    req: AnalyzeRequest,
    request: Request | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    heartbeat_interval: float = 15.0,
) -> AsyncIterator[str]:
    """True Multi-Agent Orchestration:
    Stage 1 (Casting) -> Stage 2 (Concurrent Isolated Darkrooms) -> Stage 3 (Roundtable) -> Stage 4 (Director).
    """
    api_key, base_url = get_api_config()
    base_system_prompt = build_system_prompt(req.model_dump())

    yield build_sse_message("mode_resolved", mode="multi_agent", auto_fallback=False)
    yield build_sse_message("status", label="正在校验模型通道并启动真·多 Agent 并发隔离编排")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)

    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        # Stage 1: Topic Deconstruction & Dynamic Casting
        yield build_sse_message("status", label="Stage 1/4 · 正在拆解话题与核心冲突轴")
        casting_payload: dict[str, Any] = {
            "model": req.model,
            "messages": [
                {"role": "system", "content": base_system_prompt},
                {"role": "user", "content": build_casting_prompt(req)},
            ],
            "max_tokens": compute_casting_max_tokens(req),
        }
        casting_task = asyncio.create_task(
            request_text_completion(client, base_url, headers, casting_payload, retries=2)
        )

        wait_step = 0
        casting_wait_labels = [
            "选角模型正在压缩结构化阵容",
            "选角模型正在校正冲突轴与角色差异",
            "选角耗时较长，正在保持连接心跳",
        ]
        try:
            while not casting_task.done():
                if await _is_disconnected(request):
                    casting_task.cancel()
                    await asyncio.gather(casting_task, return_exceptions=True)
                    return
                try:
                    await asyncio.wait_for(asyncio.shield(casting_task), timeout=min(12.0, heartbeat_interval))
                except asyncio.TimeoutError:
                    yield build_sse_message("heartbeat")
                    yield build_sse_message(
                        "status",
                        label=casting_wait_labels[min(wait_step, len(casting_wait_labels) - 1)],
                    )
                    wait_step += 1

            raw_casting_text = await casting_task
            casting, used_fallback = parse_or_fallback_casting(raw_casting_text, req)
        except asyncio.CancelledError:
            casting_task.cancel()
            await asyncio.gather(casting_task, return_exceptions=True)
            raise
        except Exception as exc:
            # If upstream itself failed (e.g. 401/500), surface error; if JSON malformed, parse_or_fallback handles it
            if isinstance(exc, (httpx.HTTPError, RuntimeError)) and "选角" not in str(exc):
                raise
            casting = parse_or_fallback_casting("", req)[0]
            used_fallback = True

        if await _is_disconnected(request):
            return

        if used_fallback:
            yield build_sse_message(
                "status",
                label="选角返回非标准 JSON，已自动启用自适应冲突阵容兜底",
            )

        yield build_sse_message(
            "casting",
            issue_type=casting["issue_type"],
            topic_deconstruction=casting["topic_deconstruction"],
            conflict_axes=casting["conflict_axes"],
            agents=casting["agents"],
        )

        # Stage 2: Concurrent Physical-Context-Isolated Darkroom Monologues
        agents = casting["agents"]
        total_agents = len(agents)
        concurrency = min(get_max_concurrent_agents(), total_agents)
        yield build_sse_message(
            "status",
            label=f"Stage 2/4 · 已召唤 {total_agents} 位 Agent 并发进入独立暗房（并发度 {concurrency}，零上下文串味）",
        )

        agent_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        semaphore = asyncio.Semaphore(concurrency)
        agent_tasks = [
            asyncio.create_task(
                run_isolated_agent_stream(
                    client,
                    base_url,
                    headers,
                    req,
                    casting,
                    agent,
                    agent_queue,
                    semaphore,
                    heartbeat_interval=heartbeat_interval,
                )
            )
            for agent in agents
        ]
        gather_task = asyncio.gather(*agent_tasks, return_exceptions=True)

        loop = asyncio.get_running_loop()
        last_activity = loop.time()
        try:
            while not gather_task.done() or not agent_queue.empty():
                if await _is_disconnected(request):
                    for t in agent_tasks:
                        t.cancel()
                    await asyncio.gather(*agent_tasks, return_exceptions=True)
                    return

                try:
                    event = await asyncio.wait_for(agent_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if loop.time() - last_activity >= heartbeat_interval:
                        last_activity = loop.time()
                        yield build_sse_message("heartbeat")
                    continue

                last_activity = loop.time()
                event_type = event.get("type", "status")
                payload_rest = {k: v for k, v in event.items() if k != "type"}
                yield build_sse_message(event_type, **payload_rest)

            raw_results = await gather_task
        except asyncio.CancelledError:
            for t in agent_tasks:
                t.cancel()
            await asyncio.gather(*agent_tasks, return_exceptions=True)
            raise

        agent_outputs: list[dict[str, Any]] = []
        errors: list[Exception] = []
        for res in raw_results:
            if isinstance(res, dict) and res.get("monologue"):
                agent_outputs.append(res)
            elif isinstance(res, Exception):
                errors.append(res)

        if len(agent_outputs) < min(2, total_agents):
            first_err = format_exception_message(errors[0]) if errors else "所有 Agent 均未返回有效独白"
            raise RuntimeError(f"暗房并发推演失败：{first_err}")

        if errors:
            yield build_sse_message(
                "status",
                label=f"暗房阶段已完成（{len(agent_outputs)}/{total_agents} 位成功发言，已自动隔离异常节点）",
            )

        if await _is_disconnected(request):
            return

        # Stage 3: Optional Roundtable Clash (Pro / Deep / Ultra / Flagship)
        roundtable_markdown = ""
        if should_include_roundtable(req):
            yield build_sse_message("roundtable_start", label="Stage 3/4 · 暗房门打开，圆桌激辩开始正面交锋")
            roundtable_prompt = build_roundtable_prompt(req, casting, agent_outputs)
            roundtable_system_prompt = build_system_prompt(
                {
                    **req.model_dump(),
                    "issue_type": casting["issue_type"],
                    "agent_count": str(len(agent_outputs)),
                }
            )
            roundtable_payload: dict[str, Any] = {
                "model": req.model,
                "messages": [
                    {"role": "system", "content": roundtable_system_prompt},
                    {"role": "user", "content": roundtable_prompt},
                ],
                "max_tokens": compute_roundtable_max_tokens(req),
                "stream": True,
            }

            roundtable_parts: list[str] = []
            for continuation_round in range(2):
                finish_reason = ""
                async for event in stream_text_completion(
                    client,
                    base_url,
                    headers,
                    roundtable_payload,
                    heartbeat_interval=heartbeat_interval,
                ):
                    if await _is_disconnected(request):
                        return
                    if event["type"] == "heartbeat":
                        yield build_sse_message("heartbeat")
                        continue
                    if event["type"] == "content":
                        roundtable_parts.append(event["content"])
                        yield build_sse_message("roundtable_chunk", content=event["content"])
                    elif event["type"] == "finish":
                        finish_reason = event.get("finish_reason") or ""

                if finish_reason != "length" or continuation_round >= 1:
                    break

                roundtable_payload = {
                    "model": req.model,
                    "messages": [
                        {"role": "system", "content": roundtable_system_prompt},
                        {"role": "user", "content": roundtable_prompt},
                        {"role": "assistant", "content": "".join(roundtable_parts)},
                        {
                            "role": "user",
                            "content": "请从刚才中断处继续写完剩余的圆桌激辩内容，不要重复已经出现过的观点或句子。",
                        },
                    ],
                    "max_tokens": max(2800, min(compute_roundtable_max_tokens(req), 8000)),
                    "stream": True,
                }

            roundtable_markdown = "".join(roundtable_parts).strip()
            yield build_sse_message("roundtable_done")

        if await _is_disconnected(request):
            return

        # Stage 4: Director Synthesis Report
        yield build_sse_message("director_start", label="Stage 4/4 · 局长正在整合所有暗房材料与行动建议")
        director_prompt = build_director_prompt(req, casting, agent_outputs, roundtable_markdown)
        director_system_prompt = build_system_prompt(
            {
                **req.model_dump(),
                "issue_type": casting["issue_type"],
                "agent_count": str(len(agent_outputs)),
            }
        )
        director_payload: dict[str, Any] = {
            "model": req.model,
            "messages": [
                {"role": "system", "content": director_system_prompt},
                {"role": "user", "content": director_prompt},
            ],
            "max_tokens": compute_director_max_tokens(req),
            "stream": True,
        }

        first_director_content = False
        director_parts: list[str] = []
        for continuation_round in range(2):
            finish_reason = ""
            async for event in stream_text_completion(
                client,
                base_url,
                headers,
                director_payload,
                heartbeat_interval=heartbeat_interval,
            ):
                if await _is_disconnected(request):
                    return
                if event["type"] == "heartbeat":
                    yield build_sse_message("heartbeat")
                    continue
                if event["type"] == "content":
                    if not first_director_content:
                        first_director_content = True
                        yield build_sse_message("status", label="局长整合报告已开始流式生成")
                    director_parts.append(event["content"])
                    yield build_sse_message("director_chunk", content=event["content"])
                elif event["type"] == "finish":
                    finish_reason = event.get("finish_reason") or ""

            if finish_reason != "length" or continuation_round >= 1:
                break

            yield build_sse_message("status", label="局长报告篇幅较长，正在自动续写剩余章节")
            director_payload = {
                "model": req.model,
                "messages": [
                    {"role": "system", "content": director_system_prompt},
                    {"role": "user", "content": director_prompt},
                    {"role": "assistant", "content": "".join(director_parts)},
                    {
                        "role": "user",
                        "content": "请从刚才中断处继续写完剩余内容，不要重复已输出的标题或段落，直到完整结束。",
                    },
                ],
                "max_tokens": max(3600, min(compute_max_tokens(req), 12000)),
                "stream": True,
            }

        if not first_director_content:
            raise RuntimeError("局长阶段没有返回可显示的正文内容")

        yield build_sse_message("director_done")
        yield build_sse_message("status", label="推演完成，全部材料已归档")
        yield build_sse_message("done")


async def stream_single_pass_analysis(
    req: AnalyzeRequest,
    request: Request | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    heartbeat_interval: float = 15.0,
) -> AsyncIterator[str]:
    """Rapid Single-Stream Prompt Orchestration for low-token fast deductions."""
    api_key, base_url = get_api_config()
    system_prompt = build_system_prompt(req.model_dump())

    yield build_sse_message("mode_resolved", mode="single_stream", auto_fallback=False)
    yield build_sse_message("status", label="已启动极速单流推演模式 · 正在请求流式生成")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    user_prompt = f"请严格按照推演局完整流程，对以下议题展开结构化多维推演：\n\n{req.topic.strip()}"
    payload: dict[str, Any] = {
        "model": req.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": compute_max_tokens(req),
        "stream": True,
    }

    timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        accumulated: list[str] = []
        first_chunk = False
        for continuation_round in range(2):
            finish_reason = ""
            async for event in stream_text_completion(
                client,
                base_url,
                headers,
                payload,
                heartbeat_interval=heartbeat_interval,
            ):
                if await _is_disconnected(request):
                    return
                if event["type"] == "heartbeat":
                    yield build_sse_message("heartbeat")
                    continue
                if event["type"] == "content":
                    if not first_chunk:
                        first_chunk = True
                        yield build_sse_message("status", label="正在流式输出推演全文")
                    accumulated.append(event["content"])
                    yield build_sse_message("chunk", content=event["content"])
                elif event["type"] == "finish":
                    finish_reason = event.get("finish_reason") or ""

            if finish_reason != "length" or continuation_round >= 1:
                break

            yield build_sse_message("status", label="单流输出达到单轮上限，正在续写剩余章节")
            payload = {
                "model": req.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": "".join(accumulated)},
                    {
                        "role": "user",
                        "content": "请从刚才中断处继续输出剩余章节，不要重复已生成的内容，直至完整收尾。",
                    },
                ],
                "max_tokens": max(3200, min(compute_max_tokens(req), 10000)),
                "stream": True,
            }

        if not first_chunk:
            raise RuntimeError("模型未返回任何有效内容")

        yield build_sse_message("status", label="极速单流推演已完成")
        yield build_sse_message("done")


async def stream_analysis(
    req: AnalyzeRequest,
    request: Request | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    heartbeat_interval: float = 15.0,
    demo_chunk_delay: float = 0.02,
) -> AsyncIterator[str]:
    """Top-level SSE dispatcher across multi_agent, single_stream, and offline demo modes."""
    try:
        mode = normalize_orchestration_mode(req.orchestration_mode)

        if mode == "demo":
            async for frame in stream_demo_multi_agent(
                req,
                request,
                auto_fallback=False,
                chunk_delay=demo_chunk_delay,
            ):
                yield frame
            return

        if not has_api_credentials() and transport is None:
            if req.allow_demo_fallback:
                if mode == "single_stream":
                    async for frame in stream_demo_single_stream(
                        req,
                        request,
                        auto_fallback=True,
                        chunk_delay=demo_chunk_delay,
                    ):
                        yield frame
                else:
                    async for frame in stream_demo_multi_agent(
                        req,
                        request,
                        auto_fallback=True,
                        chunk_delay=demo_chunk_delay,
                    ):
                        yield frame
                return
            raise RuntimeError("未配置有效 API Key，请在 .env 中设置 OPENAI_API_KEY 或切换至离线演示模式")

        if mode == "single_stream":
            async for frame in stream_single_pass_analysis(
                req,
                request,
                transport=transport,
                heartbeat_interval=heartbeat_interval,
            ):
                yield frame
            return

        async for frame in stream_multi_agent_analysis(
            req,
            request,
            transport=transport,
            heartbeat_interval=heartbeat_interval,
        ):
            yield frame

    except asyncio.CancelledError:
        return
    except httpx.HTTPStatusError as exc:
        yield build_sse_message("error", content=extract_error_message(exc.response))
    except httpx.ReadTimeout:
        yield build_sse_message("error", content="中转站响应超时，请稍后重试或切换模型")
    except Exception as exc:
        yield build_sse_message("error", content=format_exception_message(exc))
