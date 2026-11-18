"""Data models, token budgeting, casting normalization, and schema validation."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from .config import (
    DEFAULT_AGENT_NAMES,
    DEFAULT_VOICE_PROFILES,
    ORCHESTRATION_MODES,
    SCHEMAS_DIR,
)


class AnalyzeRequest(BaseModel):
    topic: str
    model: str = "claude-opus-4-6-thinking"
    depth: str = "standard"
    audience: str = "general"
    agent_count: str = "auto"
    issue_type: str = "自动判断"
    active_modules: list[str] = Field(default_factory=list)
    focus_perspectives: str = ""
    context: str = ""
    extra_instructions: str = ""
    orchestration_mode: str = "multi_agent"
    allow_demo_fallback: bool = True


def parse_agent_count(value: str | int | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def normalize_depth_key(depth: str) -> str:
    raw = str(depth or "standard").strip().lower()
    if raw == "deep":
        return "pro"
    if raw == "flagship":
        return "ultra"
    if raw in {"quick", "standard", "pro", "ultra"}:
        return raw
    return "standard"


def normalize_orchestration_mode(mode: str | None) -> str:
    raw = str(mode or "multi_agent").strip().lower().replace("-", "_")
    if raw in ORCHESTRATION_MODES:
        return raw
    return "multi_agent"


def should_include_roundtable(req: AnalyzeRequest) -> bool:
    return normalize_depth_key(req.depth) in {"pro", "ultra"}


def compute_max_tokens(req: AnalyzeRequest) -> int:
    """Compute dynamic max_tokens budget (up to 12,800-16,000 for flagship/ultra)."""
    depth_key = normalize_depth_key(req.depth)
    depth_tokens = {
        "quick": 3200,
        "standard": 5600,
        "pro": 9600,
        "ultra": 12800,
    }
    max_tokens = depth_tokens.get(depth_key, 5600)
    max_tokens += len(req.active_modules) * 550

    agent_count = parse_agent_count(req.agent_count)
    if agent_count:
        max_tokens += max(agent_count - 4, 0) * 350

    if req.context.strip():
        max_tokens += min(len(req.context.strip()) // 6, 1200)

    return max(2400, min(max_tokens, 16000))


def compute_casting_max_tokens(req: AnalyzeRequest) -> int:
    depth_key = normalize_depth_key(req.depth)
    requested = parse_agent_count(req.agent_count) or 5
    max_tokens = 2400 + requested * 800
    max_tokens += len(req.active_modules) * 120

    if depth_key in {"pro", "ultra"}:
        max_tokens += 450
    if depth_key == "ultra":
        max_tokens += 450

    if req.context.strip():
        max_tokens += min(len(req.context.strip()) // 10, 500)

    return max(3200, min(max_tokens, 7200))


def compute_agent_max_tokens(req: AnalyzeRequest) -> int:
    depth_key = normalize_depth_key(req.depth)
    base_tokens = {
        "quick": 1100,
        "standard": 2000,
        "pro": 3400,
        "ultra": 4800,
    }
    max_tokens = base_tokens.get(depth_key, 2000)
    if req.context.strip():
        max_tokens += min(len(req.context.strip()) // 14, 500)
    return max(900, min(max_tokens, 5600))


def compute_roundtable_max_tokens(req: AnalyzeRequest) -> int:
    depth_key = normalize_depth_key(req.depth)
    base_tokens = {
        "pro": 4800,
        "ultra": 8200,
    }
    max_tokens = base_tokens.get(depth_key, 0)
    max_tokens += len(req.active_modules) * 200

    agent_count = parse_agent_count(req.agent_count)
    if agent_count:
        max_tokens += max(agent_count - 4, 0) * 450

    if req.context.strip():
        max_tokens += min(len(req.context.strip()) // 8, 800)

    return max(3200, min(max_tokens, 11000))


def compute_director_max_tokens(req: AnalyzeRequest) -> int:
    return max(4800, min(compute_max_tokens(req) + 1200, 16000))


def clean_text(value: Any, fallback: str = "未说明") -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def clean_list(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        if items:
            return items
    return list(fallback)


def pick_agent_name(index: int) -> str:
    if 1 <= index <= len(DEFAULT_AGENT_NAMES):
        return DEFAULT_AGENT_NAMES[index - 1]
    return f"角色{index}"


def pick_voice_profile(index: int) -> dict[str, Any]:
    base = DEFAULT_VOICE_PROFILES[(index - 1) % len(DEFAULT_VOICE_PROFILES)]
    return {
        "sentence_length_tendency": str(base["sentence_length_tendency"]),
        "abstraction_preference": str(base["abstraction_preference"]),
        "expression_habits": list(base["expression_habits"]),  # type: ignore[arg-type]
        "emotion_intensity": str(base["emotion_intensity"]),
        "reasoning_moves": list(base["reasoning_moves"]),  # type: ignore[arg-type]
    }


def resolve_agent_display_name(agent: dict[str, Any], index: int) -> str:
    raw_name = str(agent.get("display_name") or agent.get("code_name") or "").strip()
    return clean_text(raw_name, pick_agent_name(index))


def resolve_agent_alias(agent: dict[str, Any]) -> str:
    raw_alias = str(agent.get("alias") or agent.get("role_tag") or "").strip()
    if raw_alias:
        return raw_alias

    dimensions = clean_list(agent.get("dimensions"), [])
    if dimensions:
        return dimensions[0]
    return "关键视角"


def agent_display_name(agent: dict[str, Any]) -> str:
    return clean_text(agent.get("display_name"), clean_text(agent.get("id"), "未命名角色"))


def normalize_voice_profile(data: Any, index: int) -> dict[str, Any]:
    base = pick_voice_profile(index)
    source = data if isinstance(data, dict) else {}
    return {
        "sentence_length_tendency": clean_text(
            source.get("sentence_length_tendency"), base["sentence_length_tendency"]
        ),
        "abstraction_preference": clean_text(
            source.get("abstraction_preference"), base["abstraction_preference"]
        ),
        "expression_habits": clean_list(source.get("expression_habits"), base["expression_habits"])[:3],
        "emotion_intensity": clean_text(source.get("emotion_intensity"), base["emotion_intensity"]),
        "reasoning_moves": clean_list(source.get("reasoning_moves"), base["reasoning_moves"])[:3],
    }


def extract_age_label(raw_age: Any, identity: str) -> str:
    age_text = str(raw_age).strip() if raw_age is not None else ""
    if age_text:
        if re.fullmatch(r"\d{1,2}", age_text):
            return f"{age_text}岁"
        return age_text

    match = re.search(r"(\d{1,2})岁", identity or "")
    if match:
        return f"{match.group(1)}岁"
    return "年龄未说明"


def normalize_topic_deconstruction(data: Any) -> dict[str, Any]:
    source = data if isinstance(data, dict) else {}
    return {
        "surface_conflict": clean_text(source.get("surface_conflict")),
        "real_dispute": clean_text(source.get("real_dispute")),
        "key_variables": clean_list(source.get("key_variables"), ["关键变量待进一步确认"]),
        "loud_but_minor": clean_text(source.get("loud_but_minor")),
        "silent_but_powerful": clean_text(source.get("silent_but_powerful")),
    }


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract and parse a JSON object from LLM text, repairing common formatting quirks."""
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("选角阶段没有返回可解析的 JSON")

    candidate = cleaned[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        repaired = re.sub(r",(\s*[}\]])", r"\1", candidate)
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"选角 JSON 解析失败: {exc.msg}") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError("选角 JSON 顶层结构必须为对象")
    return parsed


def normalize_casting(casting: dict[str, Any], req: AnalyzeRequest) -> dict[str, Any]:
    if not isinstance(casting, dict):
        raise RuntimeError("选角阶段返回格式异常")

    requested_count = parse_agent_count(req.agent_count)
    raw_agents = casting.get("agents")
    raw_agent_count = len(raw_agents) if isinstance(raw_agents, list) else 0
    if requested_count is None:
        target_count = max(4, min(raw_agent_count or 4, 8))
    else:
        target_count = max(4, min(requested_count, 10))

    conflict_axes = clean_list(casting.get("conflict_axes"), ["利益分配", "风险承担", "时间尺度"])
    conflict_axes = conflict_axes[:5]
    if len(conflict_axes) < 3:
        conflict_axes.extend(["信息差", "行动能力"])
        conflict_axes = conflict_axes[:3]

    if not isinstance(raw_agents, list) or not raw_agents:
        raise RuntimeError("选角阶段没有返回有效 Agent 阵容")

    agents: list[dict[str, Any]] = []
    for index, agent in enumerate(raw_agents[:target_count], start=1):
        if not isinstance(agent, dict):
            continue
        identity = clean_text(agent.get("identity"))
        agents.append(
            {
                "id": clean_text(agent.get("id"), f"agent_{index}"),
                "display_name": resolve_agent_display_name(agent, index),
                "alias": resolve_agent_alias(agent),
                "age": extract_age_label(agent.get("age"), identity),
                "identity": identity,
                "core_interest": clean_text(agent.get("core_interest")),
                "main_fear": clean_text(agent.get("main_fear")),
                "info_type": clean_text(agent.get("info_type")),
                "dimensions": clean_list(agent.get("dimensions"), ["关键维度待补充"]),
                "blind_spot": clean_text(agent.get("blind_spot")),
                "why_selected": clean_text(agent.get("why_selected")),
                "voice_profile": normalize_voice_profile(agent.get("voice_profile"), index),
            }
        )

    if len(agents) < 4:
        raise RuntimeError("选角阶段返回的 Agent 数量不足，至少需要 4 个")

    issue_type = (
        req.issue_type
        if req.issue_type != "自动判断"
        else clean_text(casting.get("issue_type"), "复合型")
    )

    return {
        "issue_type": issue_type,
        "topic_deconstruction": normalize_topic_deconstruction(casting.get("topic_deconstruction")),
        "conflict_axes": conflict_axes,
        "agents": agents,
    }


def infer_issue_type_from_topic(topic: str, explicit: str = "自动判断") -> str:
    if explicit and explicit != "自动判断":
        return explicit
    text = str(topic or "")
    rules = [
        ("科技冲击型", r"AI|大模型|机器人|自动化|算法|芯片|自动驾驶|程序员|开源|GitHub|智能"),
        ("社会舆论型", r"短视频|热搜|网红|舆论|流量|粉丝|平台内容|青少年|沉迷"),
        ("商业决策型", r"创业|辞职|开店|副业|价格战|带货|直播|实体店|融资|出海|商业"),
        ("组织管理型", r"996|加班|裁员|考公|跳槽|绩效|远程办公|管理|汇报|职场"),
        ("政策影响型", r"碳中和|延迟退休|政策|监管|医保|社保|税|限制|新规"),
        ("代际文化型", r"买房|婚育|结婚|生娃|大学|学历|父母|养老|年轻人"),
        ("消费体验型", r"消费降级|平替|涨价|预制菜|会员|性价比|智商税"),
    ]
    for label, pattern in rules:
        if re.search(pattern, text, flags=re.I):
            return label
    return "复合型"


def default_agent_count_for_depth(req: AnalyzeRequest) -> int:
    explicit = parse_agent_count(req.agent_count)
    if explicit is not None:
        return max(4, min(explicit, 10))
    depth_key = normalize_depth_key(req.depth)
    return {"quick": 4, "standard": 4, "pro": 5, "ultra": 6}.get(depth_key, 4)


def build_fallback_casting(req: AnalyzeRequest) -> dict[str, Any]:
    """Build a topic-aware fallback casting roster when upstream JSON parsing fails."""
    topic = req.topic.strip() or "当前争议议题"
    issue_type = infer_issue_type_from_topic(topic, req.issue_type)
    count = default_agent_count_for_depth(req)

    archetypes = [
        {
            "display_name": "林岚",
            "alias": "直接承压当事人",
            "age": "28岁",
            "identity": f"围绕「{topic}」最先感受到冲击的一线从业者",
            "core_interest": "保住当前稳定现金流与个人选择空间",
            "main_fear": "规则突变后自己承担全部转型成本",
            "info_type": "每天亲历的一线体感与身边同行样本",
            "dimensions": ["直接承受后果", "高试错成本"],
            "blind_spot": "容易把眼前摩擦放大成不可逆终局",
            "why_selected": "最先承接冲击、对变化痛感最真实",
        },
        {
            "display_name": "周明远",
            "alias": "算账型资源决策者",
            "age": "41岁",
            "identity": "手握预算与人员配置权的业务负责人",
            "core_interest": "在投入可控前提下守住效率与利润率",
            "main_fear": "跟风投入后ROI失控，或慢半拍被对手甩开",
            "info_type": "经营账本、采购成本与组织执行损耗",
            "dimensions": ["结果影响力", "成本收益核算"],
            "blind_spot": "习惯把人的适应阵痛简化为表格指标",
            "why_selected": "手里握有实际资源开关，决定变化落地的速度",
        },
        {
            "display_name": "陈素芬",
            "alias": "家庭账本守门人",
            "age": "37岁",
            "identity": "需要兼顾家庭稳定与下一代预期的普通市民家长",
            "core_interest": "生活秩序可预期，别让家庭跟着折腾踩空",
            "main_fear": "外部风向一年一变，普通家庭替不确定性买单",
            "info_type": "日常生活开支、亲友圈经验与公开资讯",
            "dimensions": ["大众生活体感", "保守防御"],
            "blind_spot": "信息主要来自二手传播，容易受焦虑叙事牵引",
            "why_selected": "代表沉默大多数的真实生活约束与风险厌恶",
        },
        {
            "display_name": "沈知行",
            "alias": "制度与规则传导者",
            "age": "45岁",
            "identity": "熟悉行业合规边界与公共治理流程的制度执行人",
            "core_interest": "风险不出底线事故，各方摩擦留在可控框架内",
            "main_fear": "一放就乱引发连锁风险，或一管就死伤及基本盘",
            "info_type": "政策执行口径、投诉纠纷案例与合规边界",
            "dimensions": ["制度端视角", "底线治理"],
            "blind_spot": "对民间自发创新与灰色过渡地带的弹性估计偏保守",
            "why_selected": "补齐制度规则与治理传导这一决定性约束维度",
        },
        {
            "display_name": "陆野",
            "alias": "顺势套利行动派",
            "age": "31岁",
            "identity": f"专门在「{topic}」结构变化里寻找新机会的独立操盘者",
            "core_interest": "趁旧秩序松动快速抢占新入口和增量红利",
            "main_fear": "窗口期太短，大平台或强监管进场后空间迅速收窄",
            "info_type": "早期转化数据、灰测反馈与套利路径",
            "dimensions": ["激进下注", "机会捕捉"],
            "blind_spot": "高估个人顺风局经验，低估大多数人的迁移门槛",
            "why_selected": "揭示谁最先在变化中行动并吃走第一波红利",
        },
        {
            "display_name": "顾清河",
            "alias": "长周期结构观察者",
            "age": "50岁",
            "identity": "跟踪产业与社会变迁二十年的独立研究员",
            "core_interest": "厘清三年以上真正起作用的结构性变量",
            "main_fear": "公众被短期口水战消耗注意力，错过关键窗口",
            "info_type": "跨周期历史对比与多行业迁移样本",
            "dimensions": ["长期视野", "结构分析"],
            "blind_spot": "看长周期很准，但容易轻视当事人眼下过冬的燃眉之急",
            "why_selected": "拉开时间尺度，区分短期情绪泡沫与长期趋势",
        },
        {
            "display_name": "唐小满",
            "alias": "舆论放大器创作者",
            "age": "26岁",
            "identity": "靠热点议题做深度拆解与情绪共鸣的自媒体主理人",
            "core_interest": "抓准大众最痛的情绪切口，拿到高转发与讨论度",
            "main_fear": "温和客观没人看，观点太极端又容易反噬翻车",
            "info_type": "评论区高频情绪词、完播率与转发偏好",
            "dimensions": ["舆论塑造", "传播机制"],
            "blind_spot": "容易把评论区声量误判成真实世界的筹码分布",
            "why_selected": "解释为什么网上最响的声音往往偏离真实决策核心",
        },
        {
            "display_name": "老赵",
            "alias": "中层夹心执行者",
            "age": "39岁",
            "identity": "既要向上交结果又要向下稳人心的基层团队主管",
            "core_interest": "上面定下来的动作能在现场跑通，别全卡在自己手里",
            "main_fear": "指标层层加码而资源不到位，最后两头受气背锅",
            "info_type": "现场落地阻力、人员配合度与真实返工率",
            "dimensions": ["压力传导", "现场执行"],
            "blind_spot": "精力被日常救火占满，缺少跳出局部看全局的余地",
            "why_selected": "还原政策或战略落地时最真实的中间层摩擦",
        },
        {
            "display_name": "许诺",
            "alias": "谨慎观望新入局者",
            "age": "23岁",
            "identity": "正准备做人生或职业关键选择的年轻入局者",
            "core_interest": "看清未来三五年哪条路还有上升通道",
            "main_fear": "按上一代经验选错方向，刚起步就撞上收缩期",
            "info_type": "同龄人求职样本、社交平台测评与前辈劝退帖",
            "dimensions": ["代际入口", "路径选择"],
            "blind_spot": "样本偏小且未经历完整周期，容易在乐观和悲观间摇摆",
            "why_selected": "体现增量人群如何用脚投票改写未来供需",
        },
        {
            "display_name": "韩牧",
            "alias": "外部资本评估人",
            "age": "35岁",
            "identity": "用真金白银评估赔率与退出路径的一级市场投资经理",
            "core_interest": "找到确定性最高的赔率结构与头部赢家",
            "main_fear": "叙事很热闹但商业闭环算不过账",
            "info_type": "行业渗透率曲线、头部玩家动向与资本流向",
            "dimensions": ["资本投票", "赔率思维"],
            "blind_spot": "只关心能规模化的头部赢家，对长尾受损者缺乏体感",
            "why_selected": "提供冷峻的资金流向与赔率判断视角",
        },
    ]

    raw_agents = [
        {
            "id": f"agent_{idx}",
            **archetypes[idx - 1],
            "voice_profile": pick_voice_profile(idx),
        }
        for idx in range(1, count + 1)
    ]

    raw_casting = {
        "issue_type": issue_type,
        "topic_deconstruction": {
            "surface_conflict": f"围绕「{topic}」，舆论表面在争论态度好坏、对错站队与情绪判断",
            "real_dispute": "实际在争夺收益归谁拿走、转型成本归谁买单，以及谁拥有按下开关的选择权",
            "key_variables": [
                "真实成本与收益账本能否跑通",
                "制度规则与平台默认机制如何设定",
                "普通当事人的替代选项与迁移缓冲期",
            ],
            "loud_but_minor": "社交平台上非黑即白的极端个案与道德化口号",
            "silent_but_powerful": "预算分配者、规则制定者以及用脚投票的真实资金与时间流向",
        },
        "conflict_axes": [
            "收益获取者 vs 成本承担者",
            "短期止损算账 vs 长期结构演变",
            "高容错有按钮者 vs 高摩擦被动承受者",
            "舆论高声量叙事 vs 现场真实约束",
        ],
        "agents": raw_agents,
    }
    return normalize_casting(raw_casting, req)


def parse_or_fallback_casting(raw_text: str, req: AnalyzeRequest) -> tuple[dict[str, Any], bool]:
    """Parse LLM casting JSON, falling back cleanly to a topic-aware roster on malformed output."""
    try:
        parsed = extract_json_object(raw_text)
        return normalize_casting(parsed, req), False
    except Exception:
        return build_fallback_casting(req), True


def load_analysis_schema() -> dict[str, Any]:
    schema_path = SCHEMAS_DIR / "analysis.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _validate_node(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            errors.append(f"{path}: expected object, got {type(value).__name__}")
            return
        for req_key in schema.get("required", []):
            if req_key not in value:
                errors.append(f"{path}.{req_key}: missing required property")
        props = schema.get("properties", {})
        for key, prop_schema in props.items():
            if key in value and isinstance(prop_schema, dict):
                _validate_node(value[key], prop_schema, f"{path}.{key}", errors)
    elif expected_type == "array":
        if not isinstance(value, list):
            errors.append(f"{path}: expected array, got {type(value).__name__}")
            return
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{path}: length {len(value)} < minItems {min_items}")
        if isinstance(max_items, int) and len(value) > max_items:
            errors.append(f"{path}: length {len(value)} > maxItems {max_items}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                _validate_node(item, item_schema, f"{path}[{idx}]", errors)
    elif expected_type == "string":
        if not isinstance(value, str):
            errors.append(f"{path}: expected string, got {type(value).__name__}")
        elif not value.strip():
            errors.append(f"{path}: expected non-empty string")


def validate_against_analysis_schema(
    instance: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> list[str]:
    """Validate a structured analysis dictionary against schemas/analysis.json."""
    active_schema = schema if schema is not None else load_analysis_schema()
    errors: list[str] = []
    _validate_node(instance, active_schema, "$", errors)
    return errors
