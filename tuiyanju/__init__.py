"""TuiYanJu (推演局 · Dynamic Cognitive Orchestrator) core backend package."""

from .config import BASE_DIR, MODEL_LABELS, MODULES_CATALOG, MODULES_MAP, has_api_credentials
from .models import AnalyzeRequest, compute_max_tokens, normalize_casting, should_include_roundtable
from .orchestrator import stream_analysis
from .prompts import (
    build_agent_prompt,
    build_casting_prompt,
    build_director_prompt,
    build_roundtable_prompt,
    build_runtime_prompt,
    build_system_prompt,
    load_file,
)
from .rate_limit import SlidingWindowRateLimiter

__version__ = "2.0.0"

__all__ = [
    "__version__",
    "AnalyzeRequest",
    "BASE_DIR",
    "MODEL_LABELS",
    "MODULES_CATALOG",
    "MODULES_MAP",
    "SlidingWindowRateLimiter",
    "build_agent_prompt",
    "build_casting_prompt",
    "build_director_prompt",
    "build_roundtable_prompt",
    "build_runtime_prompt",
    "build_system_prompt",
    "compute_max_tokens",
    "has_api_credentials",
    "load_file",
    "normalize_casting",
    "should_include_roundtable",
    "stream_analysis",
]
