from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._query_backend import QueryEngine


@dataclass
class EvalResult:
    total: int
    passed: int
    failed: int
    metrics: dict[str, Any]
    cases: list[dict[str, Any]]


def run_eval(graph: str | Path, eval_file: str | Path, *, llm_config: dict[str, Any] | None = None) -> EvalResult:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML required for eval files") from exc
    spec = yaml.safe_load(Path(eval_file).read_text(encoding="utf-8")) or {}
    cases = spec.get("cases") or spec.get("questions") or []
    engine = QueryEngine(graph, llm_config=llm_config)
    results: list[dict[str, Any]] = []
    passed = 0
    valid_count = 0
    exec_count = 0
    hallucination_failures = 0
    start_all = time.time()
    for case in cases:
        q = case.get("question") if isinstance(case, dict) else str(case)
        start = time.time()
        ans = engine.ask(q)
        checks = []
        ok = True
        validation_ok = bool(ans.validation.get("valid"))
        valid_count += 1 if validation_ok else 0
        exec_count += 1 if ans.row_count >= 0 and validation_ok else 0
        if case.get("min_rows") is not None:
            c = ans.row_count >= int(case["min_rows"])
            checks.append({"check": "min_rows", "expected": case["min_rows"], "actual": ans.row_count, "passed": c})
            ok = ok and c
        for needle in case.get("sparql_contains", []) or []:
            c = str(needle) in ans.sparql
            checks.append({"check": "sparql_contains", "expected": needle, "passed": c})
            ok = ok and c
        for needle in case.get("sparql_not_contains", []) or []:
            c = str(needle) not in ans.sparql
            checks.append({"check": "sparql_not_contains", "expected_absent": needle, "passed": c})
            ok = ok and c
            if not c:
                hallucination_failures += 1
        for ent in case.get("evidence_entities", []) or []:
            c = ent in ans.evidence.get("entities", [])
            checks.append({"check": "evidence_entity", "expected": ent, "actual": ans.evidence.get("entities", []), "passed": c})
            ok = ok and c
        if ok:
            passed += 1
        results.append({"question": q, "passed": ok, "duration_seconds": round(time.time() - start, 4), "sparql": ans.sparql, "row_count": ans.row_count, "validation": ans.validation, "checks": checks})
    total = len(cases)
    metrics = {
        "pass_rate": passed / total if total else 0,
        "valid_sparql_rate": valid_count / total if total else 0,
        "execution_success_rate": exec_count / total if total else 0,
        "hallucination_failure_count": hallucination_failures,
        "duration_seconds": round(time.time() - start_all, 4),
    }
    return EvalResult(total=total, passed=passed, failed=total - passed, metrics=metrics, cases=results)


def write_eval_report(result: EvalResult, path: str | Path) -> None:
    Path(path).write_text(json.dumps(result.__dict__, indent=2, default=str), encoding="utf-8")
