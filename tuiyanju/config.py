"""Configuration, constants, and environment helpers for TuiYanJu (推演局)."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = BASE_DIR / "prompts"
SCHEMAS_DIR = BASE_DIR / "schemas"
EVALS_DIR = BASE_DIR / "evals"
DOCS_DIR = BASE_DIR / "docs"

load_dotenv(BASE_DIR / ".env")

PLACEHOLDER_API_KEYS = {
    "",
    "sk-your-relay-key",
    "your-api-key",
    "your_api_key_here",
    "sk-xxx",
    "changeme",
}

ORCHESTRATION_MODES = ("multi_agent", "single_stream", "demo", "auto")

MODULES_MAP: dict[str, str] = {
    "winners": "谁会占便宜，谁会吃亏",
    "timeline": "这件事接下来会怎么发展",
    "signal": "网上热闹和真实关键分别是什么",
    "action": "下一步谁最可能先出手",
    "monitor": "后面该盯哪些变化信号",
    "appendix": "把重点整理成清单",
}

MODULES_CATALOG: list[dict[str, str]] = [
    {"id": "winners", "name": "谁会占便宜，谁会吃亏", "desc": "把得利方和吃亏方直接挑出来"},
    {"id": "timeline", "name": "这件事接下来会怎么发展", "desc": "看短期、中期、长期怎么变"},
    {"id": "signal", "name": "网上热闹和真实关键分别是什么", "desc": "分清哪些只是热搜，哪些真会改结果"},
    {"id": "action", "name": "下一步谁最可能先出手", "desc": "预测谁会先动，动作会是什么"},
    {"id": "monitor", "name": "后面该盯哪些变化信号", "desc": "给你几个后续最值得盯的观察点"},
    {"id": "appendix", "name": "把重点整理成清单", "desc": "把结论压成更容易转发和复用的清单"},
]

DEPTH_MAP: dict[str, str] = {
    "quick": "快照",
    "standard": "标准",
    "pro": "Pro 深入版",
    "ultra": "Ultra 顶配版",
    "deep": "Pro 深入版",
    "flagship": "Ultra 顶配版",
}

AUDIENCE_MAP: dict[str, str] = {
    "general": "普通读者",
    "manager": "管理层",
    "investor": "投资人",
    "researcher": "研究人员",
    "creator": "内容创作者",
}

DEFAULT_AGENT_NAMES: list[str] = [
    "小红",
    "王二",
    "阿杰",
    "老周",
    "小雨",
    "阿梅",
    "大刘",
    "阿宁",
    "阿强",
    "小北",
]

MODEL_LABELS: dict[str, str] = {
    "claude-opus-4-6-thinking": "Claude Opus 4.6 Thinking（推荐）",
    "claude-opus-4-6": "Claude Opus 4.6",
    "claude-sonnet-4-6": "Claude Sonnet 4.6（更快）",
    "gpt-5": "GPT-5",
    "gpt-4o": "GPT-4o",
    "gpt-4o-mini": "GPT-4o-mini（快）",
    "gpt-4-turbo": "GPT-4-turbo",
}

PREFERRED_MODEL_ORDER: list[str] = [
    "claude-opus-4-6-thinking",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "gpt-5",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
]

DEFAULT_VOICE_PROFILES: list[dict[str, object]] = [
    {
        "sentence_length_tendency": "短句偏多，先把态度亮出来",
        "abstraction_preference": "偏具体，只说自己碰到的事",
        "expression_habits": ["喜欢先讲眼前结论", "常把风险说得很直白"],
        "emotion_intensity": "中高，压着焦虑说",
        "reasoning_moves": ["喜欢举身边小例子", "喜欢直接下判断"],
    },
    {
        "sentence_length_tendency": "中短句为主，节奏利落",
        "abstraction_preference": "具体里带一点算账视角",
        "expression_habits": ["爱用成本收益来衡量", "说话像在做决策备忘"],
        "emotion_intensity": "偏克制，但会显得硬",
        "reasoning_moves": ["喜欢算账", "喜欢先看投入产出"],
    },
    {
        "sentence_length_tendency": "长短句混合，先铺事实再下结论",
        "abstraction_preference": "具体经验和抽象判断都会带一点",
        "expression_habits": ["习惯先交代背景", "会用转折把顾虑说出来"],
        "emotion_intensity": "中等，表面稳但内里不安",
        "reasoning_moves": ["喜欢先讲经历", "喜欢边讲边校正判断"],
    },
    {
        "sentence_length_tendency": "句子略长，像在慢慢分析",
        "abstraction_preference": "偏抽象，但会落回现实后果",
        "expression_habits": ["喜欢先拆问题", "常把话说成几层意思"],
        "emotion_intensity": "偏低，更多是冷静担心",
        "reasoning_moves": ["喜欢分层讲", "喜欢先保留再下结论"],
    },
    {
        "sentence_length_tendency": "短句和半句多，说话带点催促感",
        "abstraction_preference": "非常具体，盯着眼前压力点",
        "expression_habits": ["经常拿现实处境压一句", "会不自觉抱怨几句"],
        "emotion_intensity": "高，情绪容易露出来",
        "reasoning_moves": ["喜欢抱怨现实摩擦", "喜欢拿最近变化举例"],
    },
    {
        "sentence_length_tendency": "中句为主，像跟熟人聊天",
        "abstraction_preference": "偏具体，落点在人和生活",
        "expression_habits": ["常把话题拉回日常生活", "爱用朴素比喻但不过火"],
        "emotion_intensity": "中等，真实但不炸",
        "reasoning_moves": ["喜欢举生活例子", "喜欢从家庭账本看问题"],
    },
    {
        "sentence_length_tendency": "短中句混合，像在现场复盘",
        "abstraction_preference": "偏具体，重过程细节",
        "expression_habits": ["喜欢复述自己看见的流程", "会顺手点出执行卡点"],
        "emotion_intensity": "偏克制，更多是不耐烦",
        "reasoning_moves": ["喜欢讲执行细节", "喜欢抓关键阻塞点"],
    },
    {
        "sentence_length_tendency": "句子略长，但会突然斩钉截铁",
        "abstraction_preference": "抽象判断稍多，喜欢看趋势",
        "expression_habits": ["常先看大势再落到自己", "偶尔会下很重的判断"],
        "emotion_intensity": "中高，带明显立场",
        "reasoning_moves": ["喜欢判断趋势", "喜欢把短期和长期分开看"],
    },
    {
        "sentence_length_tendency": "中短句，像在压着火气解释",
        "abstraction_preference": "偏具体，盯住不公平感",
        "expression_habits": ["容易先说不服气的地方", "会反复强调谁在承担代价"],
        "emotion_intensity": "高，带怨气但不失真",
        "reasoning_moves": ["喜欢点名代价", "喜欢把责任归因说清楚"],
    },
    {
        "sentence_length_tendency": "长短句交替，像边想边说",
        "abstraction_preference": "抽象和具体来回切换",
        "expression_habits": ["会先犹豫一下再落判断", "喜欢补一句留后路的话"],
        "emotion_intensity": "中等偏低，更多是谨慎",
        "reasoning_moves": ["喜欢先讲可能性", "喜欢保留条件再判断"],
    },
]

DEFAULT_LOCAL_ORIGINS: list[str] = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "null",
]


def get_env_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def normalize_base_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url:
        return "https://api.openai.com/v1"

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path in ("", "/"):
        return f"{url}/v1"
    return url


def has_api_credentials() -> bool:
    api_key = get_env_value("OPENAI_API_KEY", "API_KEY")
    return bool(api_key) and api_key.lower() not in PLACEHOLDER_API_KEYS


def get_api_config() -> tuple[str, str]:
    api_key = get_env_value("OPENAI_API_KEY", "API_KEY")
    if not api_key or api_key.lower() in PLACEHOLDER_API_KEYS:
        raise RuntimeError("未配置有效 API Key，请在 .env 中设置 OPENAI_API_KEY 或 API_KEY，或使用离线演示模式")

    base_url = normalize_base_url(
        get_env_value(
            "OPENAI_BASE_URL",
            "BASE_URL",
            "OPENAI_API_BASE",
            "API_BASE_URL",
        )
    )
    return api_key, base_url


def get_cors_origins() -> list[str]:
    raw = get_env_value("CORS_ORIGINS")
    if not raw:
        return list(DEFAULT_LOCAL_ORIGINS)
    if raw == "*":
        return ["*"]
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or list(DEFAULT_LOCAL_ORIGINS)


def get_rate_limit_per_minute() -> int:
    raw = get_env_value("RATE_LIMIT_PER_MINUTE")
    if not raw:
        return 20
    try:
        return max(0, int(raw))
    except ValueError:
        return 20


def get_max_concurrent_agents() -> int:
    raw = get_env_value("MAX_CONCURRENT_AGENTS")
    if not raw:
        return 6
    try:
        return max(1, min(int(raw), 10))
    except ValueError:
        return 6
