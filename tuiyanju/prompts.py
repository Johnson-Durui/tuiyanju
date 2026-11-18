"""Prompt loading and template rendering for all orchestration stages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import AUDIENCE_MAP, BASE_DIR, DEPTH_MAP, EVALS_DIR, MODULES_MAP, PROMPTS_DIR, SCHEMAS_DIR
from .models import AnalyzeRequest, agent_display_name


def load_file(path: str) -> str:
    """Resolve and read a prompt/schema/eval asset with clean fallback paths."""
    raw = Path(path)
    name = raw.name
    candidates = [
        BASE_DIR / raw,
        PROMPTS_DIR / name,
        SCHEMAS_DIR / name,
        EVALS_DIR / name,
        BASE_DIR / name,
        BASE_DIR.parent / raw,
    ]
    for full in candidates:
        if full.is_file():
            return full.read_text(encoding="utf-8")
    raise FileNotFoundError(f"找不到文件: {path}")


def format_active_modules(active_modules: list[Any]) -> str:
    return "、".join([MODULES_MAP[m] for m in active_modules if m in MODULES_MAP]) or "无（标准模式）"


def build_prompt_context(req: dict[str, Any]) -> dict[str, str]:
    return {
        "topic": str(req.get("topic", "")),
        "issue_type": str(req.get("issue_type", "自动判断") or "自动判断"),
        "depth": DEPTH_MAP.get(str(req.get("depth", "standard")), "标准"),
        "audience": AUDIENCE_MAP.get(str(req.get("audience", "general")), "普通读者"),
        "agent_count": str(req.get("agent_count", "auto（4-8个）")),
        "active_modules": format_active_modules(req.get("active_modules", [])),
        "focus_perspectives": str(req.get("focus_perspectives", "") or "无特别指定"),
        "context": str(req.get("context", "") or "无"),
        "extra_instructions": str(req.get("extra_instructions", "") or "无"),
    }


def render_prompt(template_name: str, values: dict[str, str]) -> str:
    text = load_file(template_name)
    for key, value in values.items():
        text = text.replace(f"{{{key}}}", value)
    return text


def build_runtime_prompt(req: dict[str, Any]) -> str:
    return render_prompt("prompts/runtime.md", build_prompt_context(req))


def build_system_prompt(req: dict[str, Any]) -> str:
    system = load_file("prompts/system.md").strip()
    runtime = build_runtime_prompt(req).strip()
    return f"{system}\n\n---\n\n{runtime}"


def build_isolated_agent_system_prompt() -> str:
    """Build a strict physical-context-isolated system prompt for a single Darkroom Agent.

    Draws core isolation & language-register rules without leaking any other agent's identity or output.
    """
    full_system = load_file("prompts/system.md")
    # Keep Core Principles + Depth Spec + Quality Guardrails only (before Director multi-step workflow)
    marker = "# 议题诊断"
    idx = full_system.find(marker)
    guardrails = full_system[:idx].strip() if idx != -1 else full_system.strip()
    return (
        f"{guardrails}\n\n"
        "# 独立暗房隔离执行约束\n"
        "当前你处于【物理上下文隔离】的单人暗房通道中，只扮演用户消息里指定的唯一角色，"
        "严禁切换为推演局长，严禁输出其他角色、目录、标题或全局总结。"
    )


def format_voice_profile_for_prompt(profile: dict[str, Any]) -> str:
    return (
        f"- 句子节奏：{profile['sentence_length_tendency']}\n"
        f"- 抽象/具体倾向：{profile['abstraction_preference']}\n"
        f"- 常用表达方式：{'；'.join(profile['expression_habits'])}\n"
        f"- 情绪浓度：{profile['emotion_intensity']}\n"
        f"- 论证习惯：{'；'.join(profile['reasoning_moves'])}"
    )


def format_topic_deconstruction_for_prompt(data: dict[str, Any]) -> str:
    return (
        f"- 表层冲突：{data['surface_conflict']}\n"
        f"- 实际争议：{data['real_dispute']}\n"
        f"- 关键变量：{'；'.join(data['key_variables'])}\n"
        f"- 响但次要：{data['loud_but_minor']}\n"
        f"- 沉默但关键：{data['silent_but_powerful']}"
    )


def format_agent_roster_for_prompt(agents: list[dict[str, Any]]) -> str:
    rows = []
    for agent in agents:
        rows.append(
            f"- {agent_display_name(agent)}｜补充标签：{agent['alias']}｜年龄：{agent['age']}"
            f"｜身份：{agent['identity']}｜利益：{agent['core_interest']}"
            f"｜恐惧：{agent['main_fear']}｜维度：{' / '.join(agent['dimensions'])}"
        )
    return "\n".join(rows)


def format_agent_monologues_for_prompt(agent_outputs: list[dict[str, Any]]) -> str:
    blocks = []
    for item in agent_outputs:
        blocks.append(
            f"## {agent_display_name(item)}\n"
            f"- 补充标签：{item['alias']}\n"
            f"- 年龄：{item['age']}\n"
            f"- 身份：{item['identity']}\n"
            f"- 利益：{item['core_interest']}\n"
            f"- 恐惧：{item['main_fear']}\n"
            f"- 维度：{' / '.join(item['dimensions'])}\n"
            f"- 独白：\n{item['monologue'].strip()}\n"
        )
    return "\n".join(blocks)


def format_roundtable_for_prompt(roundtable_markdown: str) -> str:
    text = str(roundtable_markdown or "").strip()
    return text or "本轮无圆桌激辩记录（当前为标准及以下档位，或圆桌环节未触发）。"


def build_casting_prompt(req: AnalyzeRequest) -> str:
    return render_prompt("prompts/casting.md", build_prompt_context(req.model_dump()))


def build_agent_prompt(req: AnalyzeRequest, casting: dict[str, Any], agent: dict[str, Any]) -> str:
    agent_values = {
        key: (" / ".join(value) if isinstance(value, list) else str(value))
        for key, value in agent.items()
        if key != "voice_profile"
    }
    values = {
        **build_prompt_context(req.model_dump()),
        "issue_type": casting["issue_type"],
        "conflict_axes": "、".join(casting["conflict_axes"]),
        **agent_values,
        "voice_profile": format_voice_profile_for_prompt(agent["voice_profile"]),
    }
    return render_prompt("prompts/agent.md", values)


def build_roundtable_prompt(
    req: AnalyzeRequest,
    casting: dict[str, Any],
    agent_outputs: list[dict[str, Any]],
) -> str:
    values = {
        **build_prompt_context(req.model_dump()),
        "issue_type": casting["issue_type"],
        "topic_deconstruction": format_topic_deconstruction_for_prompt(casting["topic_deconstruction"]),
        "conflict_axes": "、".join(casting["conflict_axes"]),
        "agent_roster": format_agent_roster_for_prompt(casting["agents"]),
        "agent_monologues": format_agent_monologues_for_prompt(agent_outputs),
    }
    return render_prompt("prompts/roundtable.md", values)


def build_director_prompt(
    req: AnalyzeRequest,
    casting: dict[str, Any],
    agent_outputs: list[dict[str, Any]],
    roundtable_markdown: str = "",
) -> str:
    values = {
        **build_prompt_context(req.model_dump()),
        "issue_type": casting["issue_type"],
        "topic_deconstruction": format_topic_deconstruction_for_prompt(casting["topic_deconstruction"]),
        "conflict_axes": "、".join(casting["conflict_axes"]),
        "agent_roster": format_agent_roster_for_prompt(casting["agents"]),
        "agent_monologues": format_agent_monologues_for_prompt(agent_outputs),
        "roundtable_transcript": format_roundtable_for_prompt(roundtable_markdown),
    }
    return render_prompt("prompts/director.md", values)
