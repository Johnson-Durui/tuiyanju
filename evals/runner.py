"""Offline schema/dataset validator & automated LLM rubric evaluation runner for TuiYanJu."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tuiyanju.config import EVALS_DIR, SCHEMAS_DIR, get_api_config, has_api_credentials  # noqa: E402
from tuiyanju.demo import build_demo_bundle  # noqa: E402
from tuiyanju.models import (  # noqa: E402
    AnalyzeRequest,
    extract_json_object,
    validate_against_analysis_schema,
)
from tuiyanju.orchestrator import request_text_completion, stream_analysis  # noqa: E402

REQUIRED_SCHEMA_KEYS = {
    "topic_deconstruction",
    "agents",
    "director_summary",
    "action_suggestions",
    "layering",
}


def load_eval_cases(cases_path: Path | None = None) -> list[dict[str, Any]]:
    target = cases_path or (EVALS_DIR / "cases.jsonl")
    if not target.is_file():
        raise FileNotFoundError(f"未找到评测用例文件: {target}")

    cases: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"cases.jsonl 第 {line_no} 行 JSON 无效: {exc.msg}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"cases.jsonl 第 {line_no} 行必须是 JSON 对象")
        cases.append(obj)
    return cases


def parse_rubric_dimensions(rubric_path: Path | None = None) -> list[dict[str, Any]]:
    target = rubric_path or (EVALS_DIR / "rubric.md")
    if not target.is_file():
        raise FileNotFoundError(f"未找到评分标准文件: {target}")

    text = target.read_text(encoding="utf-8")
    pattern = re.compile(r"^###\s*(\d+)\.\s*(.+?)（(\d+)分[^）]*）", flags=re.M)
    dimensions: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        dimensions.append(
            {
                "index": int(match.group(1)),
                "name": match.group(2).strip(),
                "max_score": int(match.group(3)),
            }
        )
    return dimensions


def validate_eval_assets(
    *,
    schema_path: Path | None = None,
    cases_path: Path | None = None,
    rubric_path: Path | None = None,
) -> dict[str, Any]:
    """Validate schemas/analysis.json, evals/cases.jsonl, evals/rubric.md, and schema conformance."""
    errors: list[str] = []

    active_schema_path = schema_path or (SCHEMAS_DIR / "analysis.json")
    if not active_schema_path.is_file():
        errors.append(f"缺少 Schema 文件: {active_schema_path}")
        schema: dict[str, Any] = {}
    else:
        schema = json.loads(active_schema_path.read_text(encoding="utf-8"))
        if schema.get("type") != "object":
            errors.append("analysis.json 顶层 type 必须为 object")
        missing_req = REQUIRED_SCHEMA_KEYS - set(schema.get("required", []))
        if missing_req:
            errors.append(f"analysis.json 缺少必填顶层字段: {sorted(missing_req)}")

    cases = load_eval_cases(cases_path)
    if not cases:
        errors.append("evals/cases.jsonl 不能为空")

    seen_ids: set[str] = set()
    for idx, case in enumerate(cases, start=1):
        cid = str(case.get("id") or "").strip()
        topic = str(case.get("topic") or "").strip()
        issue_type = str(case.get("issue_type") or "").strip()
        expected_agents = case.get("expected_agent_types")

        if not cid:
            errors.append(f"case #{idx}: 缺少 id")
        elif cid in seen_ids:
            errors.append(f"case #{idx}: 重复 id '{cid}'")
        seen_ids.add(cid)

        if not topic:
            errors.append(f"case {cid or idx}: topic 不能为空")
        if not issue_type:
            errors.append(f"case {cid or idx}: issue_type 不能为空")
        if not isinstance(expected_agents, list) or len(expected_agents) < 4:
            errors.append(f"case {cid or idx}: expected_agent_types 至少需要 4 类角色")

    dimensions = parse_rubric_dimensions(rubric_path)
    total_points = sum(dim["max_score"] for dim in dimensions)
    if len(dimensions) != 8:
        errors.append(f"rubric.md 应包含 8 个评分维度，当前解析到 {len(dimensions)} 个")
    if total_points != 100:
        errors.append(f"rubric.md 维度满分总和应为 100 分，当前为 {total_points} 分")

    # Validate offline synthesis against schemas/analysis.json for every case
    schema_checked = 0
    if schema and cases:
        for case in cases:
            req = AnalyzeRequest(
                topic=case["topic"],
                issue_type=case.get("issue_type", "自动判断"),
                depth="pro",
                orchestration_mode="demo",
            )
            bundle = build_demo_bundle(req)
            schema_errors = validate_against_analysis_schema(bundle["structured_analysis"], schema)
            if schema_errors:
                errors.extend([f"case {case['id']} schema error: {err}" for err in schema_errors])
            schema_checked += 1

    return {
        "valid": len(errors) == 0,
        "case_count": len(cases),
        "rubric_dimensions": len(dimensions),
        "rubric_total_points": total_points,
        "schema_checked_cases": schema_checked,
        "errors": errors,
    }


def score_structural_completeness(report: dict[str, Any], include_enhancements: bool = False) -> dict[str, Any]:
    """Deterministic structural rubric check (used offline and alongside LLM judge)."""
    agents = report.get("agents", [])
    director_md = str(report.get("director_markdown") or "")
    checks = {
        "has_min_4_agents": len(agents) >= 4,
        "distinct_display_names": len({a.get("display_name") for a in agents}) == len(agents) and len(agents) > 0,
        "non_empty_monologues": all(len(str(a.get("monologue") or "").strip()) >= 40 for a in agents)
        and len(agents) > 0,
        "has_director_sections_a_to_h": all(
            marker in director_md for marker in ("表层冲突", "深层动力", "共识地带", "断层", "嗓门", "隐藏变量", "触发器", "真相")
        ),
        "has_action_suggestions": "行动建议" in director_md,
        "has_fact_layering": all(layer in director_md for layer in ("事实层", "推断层", "情绪层")),
        "has_enhancements": ("增强模块" in director_md) if include_enhancements else True,
    }
    passed = sum(1 for ok in checks.values() if ok)
    structural_score = round((passed / len(checks)) * 100, 1)
    return {
        "structural_score": structural_score,
        "checks": checks,
    }


async def collect_sse_report(
    req: AnalyzeRequest,
    *,
    demo_chunk_delay: float = 0.0,
) -> dict[str, Any]:
    """Consume stream_analysis SSE frames and assemble a structured run summary."""
    casting: dict[str, Any] = {}
    agent_map: dict[str, dict[str, Any]] = {}
    agent_order: list[str] = []
    roundtable_parts: list[str] = []
    director_parts: list[str] = []
    resolved_mode = req.orchestration_mode
    errors: list[str] = []

    async for raw_frame in stream_analysis(req, None, demo_chunk_delay=demo_chunk_delay):
        for line in raw_frame.splitlines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            etype = event.get("type")
            if etype == "mode_resolved":
                resolved_mode = event.get("mode", resolved_mode)
            elif etype == "casting":
                casting = event
                for ag in event.get("agents", []):
                    aid = ag["id"]
                    agent_map[aid] = {**ag, "monologue": ""}
                    if aid not in agent_order:
                        agent_order.append(aid)
            elif etype == "agent_start":
                ag = event.get("agent") or {}
                aid = ag.get("id", "")
                if aid and aid not in agent_map:
                    agent_map[aid] = {**ag, "monologue": ""}
                    agent_order.append(aid)
            elif etype == "agent_chunk":
                aid = event.get("agent_id", "")
                if aid in agent_map:
                    agent_map[aid]["monologue"] += event.get("content", "")
            elif etype == "roundtable_chunk":
                roundtable_parts.append(event.get("content", ""))
            elif etype == "director_chunk":
                director_parts.append(event.get("content", ""))
            elif etype == "chunk":
                director_parts.append(event.get("content", ""))
            elif etype == "error":
                errors.append(str(event.get("content") or "unknown error"))

    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "mode": resolved_mode,
        "casting": casting,
        "agents": [agent_map[aid] for aid in agent_order if aid in agent_map],
        "roundtable_markdown": "".join(roundtable_parts).strip(),
        "director_markdown": "".join(director_parts).strip(),
    }


def grade_for_score(total: float) -> str:
    if total >= 90:
        return "王炸"
    if total >= 75:
        return "优秀"
    if total >= 60:
        return "合格"
    if total >= 40:
        return "待改进"
    return "不合格"


async def judge_report_with_llm(
    case: dict[str, Any],
    report: dict[str, Any],
    rubric_text: str,
    judge_model: str,
) -> dict[str, Any]:
    """Score a generated deduction report against evals/rubric.md using an LLM judge."""
    api_key, base_url = get_api_config()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    monologues_preview = "\n\n".join(
        f"### {ag.get('display_name')}（{ag.get('alias')}）\n{ag.get('monologue', '')}"
        for ag in report.get("agents", [])
    )
    prompt = (
        "你是推演局（Dynamic Cognitive Orchestrator）的独立评测裁判。\n"
        "请严格按照以下评分标准，对待测报告逐项打分，并只输出合法 JSON（不要代码块）：\n\n"
        f"【评分标准】\n{rubric_text}\n\n"
        f"【测试用例】\nID: {case['id']}｜议题：{case['topic']}｜期望角色参考：{', '.join(case.get('expected_agent_types', []))}\n\n"
        f"【Agent 暗房独白】\n{monologues_preview or '（单流模式见正文）'}\n\n"
        f"【圆桌激辩】\n{report.get('roundtable_markdown') or '无'}\n\n"
        f"【局长报告正文】\n{report.get('director_markdown', '')}\n\n"
        "输出 JSON 格式：\n"
        '{"scores":{"casting_fit":18,"perspective_diversity":14,"stakes_clarity":14,'
        '"voice_authenticity":13,"structural_insight":14,"actionability":9,"fact_layering":5,"enhancements":4},'
        '"total_score":91,"grade":"王炸","summary":"一句话定性评价"}'
    )
    timeout = httpx.Timeout(connect=20.0, read=120.0, write=20.0, pool=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        raw = await request_text_completion(
            client,
            base_url,
            headers,
            {
                "model": judge_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1200,
            },
            retries=2,
        )
    parsed = extract_json_object(raw)
    scores = parsed.get("scores") if isinstance(parsed.get("scores"), dict) else {}
    total = float(parsed.get("total_score") or sum(float(v) for v in scores.values() if isinstance(v, (int, float))))
    return {
        "scores": scores,
        "total_score": total,
        "grade": str(parsed.get("grade") or grade_for_score(total)),
        "summary": str(parsed.get("summary") or ""),
    }


async def run_evaluation(
    *,
    mode: str = "validate",
    case_id: str | None = None,
    limit: int | None = None,
    orchestration_mode: str = "multi_agent",
    depth: str = "pro",
    model: str = "gpt-4o-mini",
    judge_model: str | None = None,
) -> dict[str, Any]:
    validation = validate_eval_assets()
    if mode == "validate" or not validation["valid"]:
        return {"mode": "validate", "validation": validation, "results": []}

    cases = load_eval_cases()
    if case_id:
        cases = [c for c in cases if c.get("id") == case_id]
    if limit and limit > 0:
        cases = cases[:limit]

    effective_mode = mode
    if effective_mode == "auto":
        effective_mode = "live" if has_api_credentials() else "demo-eval"

    if effective_mode == "live" and not has_api_credentials():
        raise RuntimeError("当前未配置有效 API Key，无法运行 --mode live（可使用 --mode validate 或 --mode demo-eval）")

    rubric_text = (EVALS_DIR / "rubric.md").read_text(encoding="utf-8")
    results: list[dict[str, Any]] = []

    for case in cases:
        run_orch_mode = "demo" if effective_mode == "demo-eval" else orchestration_mode
        req = AnalyzeRequest(
            topic=case["topic"],
            issue_type=case.get("issue_type", "自动判断"),
            depth=depth,
            model=model,
            active_modules=["winners"],
            orchestration_mode=run_orch_mode,
            allow_demo_fallback=(effective_mode != "live"),
        )
        report = await collect_sse_report(req, demo_chunk_delay=0.0)
        structural = score_structural_completeness(report, include_enhancements=True)
        entry: dict[str, Any] = {
            "id": case["id"],
            "topic": case["topic"],
            "resolved_mode": report["mode"],
            "agent_count": len(report["agents"]),
            "structural": structural,
        }
        if effective_mode == "live":
            entry["llm_judge"] = await judge_report_with_llm(
                case,
                report,
                rubric_text,
                judge_model or model,
            )
        results.append(entry)

    return {
        "mode": effective_mode,
        "validation": validation,
        "evaluated_count": len(results),
        "results": results,
    }


def run_offline_demo_evaluation(
    *,
    case_id: str | None = None,
    limit: int | None = None,
    depth: str = "pro",
) -> dict[str, Any]:
    """Run deterministic offline demo evaluation across benchmark cases without requiring sockets."""
    validation = validate_eval_assets()
    if not validation["valid"]:
        return {"mode": "demo-eval", "validation": validation, "evaluated_count": 0, "results": []}

    cases = load_eval_cases()
    if case_id:
        cases = [c for c in cases if c.get("id") == case_id]
    if limit and limit > 0:
        cases = cases[:limit]

    results: list[dict[str, Any]] = []
    for case in cases:
        req = AnalyzeRequest(
            topic=case["topic"],
            issue_type=case.get("issue_type", "自动判断"),
            depth=depth,
            active_modules=["winners"],
            orchestration_mode="demo",
        )
        bundle = build_demo_bundle(req)
        report = {
            "mode": "demo",
            "casting": bundle["casting"],
            "agents": bundle["agent_outputs"],
            "roundtable_markdown": bundle["roundtable_markdown"],
            "director_markdown": bundle["director_markdown"],
        }
        structural = score_structural_completeness(report, include_enhancements=True)
        results.append(
            {
                "id": case["id"],
                "topic": case["topic"],
                "resolved_mode": "demo",
                "agent_count": len(report["agents"]),
                "structural": structural,
            }
        )

    return {
        "mode": "demo-eval",
        "validation": validation,
        "evaluated_count": len(results),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="推演局 (TuiYanJu) 离线 Schema/Dataset 校验与自动化 Rubric 评测器"
    )
    parser.add_argument(
        "--mode",
        choices=("validate", "demo-eval", "live", "auto"),
        default="validate",
        help="validate: 离线校验 Schema/Cases/Rubric; demo-eval: 离线全链路结构评测; live: 调用真实LLM生成+裁判打分",
    )
    parser.add_argument("--case-id", help="仅运行指定用例 ID（例如 001）")
    parser.add_argument("--limit", type=int, default=None, help="限制最多运行的用例数量")
    parser.add_argument(
        "--orchestration-mode",
        choices=("multi_agent", "single_stream"),
        default="multi_agent",
        help="live 模式下的推演编排模式",
    )
    parser.add_argument("--depth", default="pro", help="分析深度（quick/standard/pro/ultra）")
    parser.add_argument("--model", default="gpt-4o-mini", help="推演使用的模型名")
    parser.add_argument("--judge-model", default=None, help="LLM 裁判模型名（默认与 --model 相同）")
    parser.add_argument("--output", default=None, help="将评测结果写入指定 JSON 文件路径")
    args = parser.parse_args(argv)

    effective_mode = args.mode
    if effective_mode == "auto":
        effective_mode = "live" if has_api_credentials() else "demo-eval"

    if effective_mode == "validate":
        summary: dict[str, Any] = {
            "mode": "validate",
            "validation": validate_eval_assets(),
            "results": [],
        }
    elif effective_mode == "demo-eval":
        summary = run_offline_demo_evaluation(
            case_id=args.case_id,
            limit=args.limit,
            depth=args.depth,
        )
    else:
        summary = asyncio.run(
            run_evaluation(
                mode=effective_mode,
                case_id=args.case_id,
                limit=args.limit,
                orchestration_mode=args.orchestration_mode,
                depth=args.depth,
                model=args.model,
                judge_model=args.judge_model,
            )
        )

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["validation"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
