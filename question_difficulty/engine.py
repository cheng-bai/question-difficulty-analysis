"""Pure, standard-library implementation of the v1.1 H/C/T/D rules.

Input dimensions and evidence are supplied by a reviewer, not inferred here.
Dependency edges express prerequisite steps. Branches are not summed into C.
"""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from math import isfinite
from statistics import mean, median, pstdev

DIMENSIONS = "KRAVPI"
WEIGHTS = tuple(map(Decimal, (".20", ".25", ".15", ".15", ".15", ".10")))


class ValidationError(ValueError):
    """Input lacks auditable evidence or violates the dependency schema."""


def rounded(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be non-empty text")


def _integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValidationError(f"{name} must be an integer in [{low}, {high}]")


def _validate(q):
    if not isinstance(q, dict):
        raise ValidationError("question must be an object")
    _text(q.get("id"), "question.id")
    if type(q.get("pending", False)) is not bool:
        raise ValidationError("pending must be boolean")
    if q.get("pending"):
        _text(q.get("issue"), "pending question.issue")
        return
    steps = q.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValidationError("steps must be a non-empty list")
    ids = set()
    for step in steps:
        if not isinstance(step, dict):
            raise ValidationError("step must be an object")
        sid = step.get("id")
        _text(sid, "step.id")
        if sid in ids:
            raise ValidationError(f"duplicate step id: {sid}")
        ids.add(sid)
        for key in ("input", "action", "output", "type_id"):
            _text(step.get(key), f"{sid}.{key}")
        dimensions = step.get("dimensions")
        evidence = step.get("dimension_evidence")
        if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
            raise ValidationError(f"{sid} requires exactly K/R/A/V/P/I")
        if not isinstance(evidence, dict):
            raise ValidationError(f"{sid} requires dimension_evidence")
        for key in DIMENSIONS:
            _integer(dimensions[key], 0, 2, f"{sid}.{key}")
            _text(evidence.get(key), f"{sid}.{key} evidence")
        deps = step.get("dependencies", [])
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
            raise ValidationError(f"{sid}.dependencies must be a list of IDs")
        if len(deps) != len(set(deps)):
            raise ValidationError(f"duplicate dependencies: {sid}")
        if step.get("repeat_group") is not None:
            _text(step["repeat_group"], f"{sid}.repeat_group")
            _text(step.get("repeat_evidence"), f"{sid}.repeat_evidence")
    by_id = {s["id"]: s for s in steps}
    for step in steps:
        for dep in step.get("dependencies", []):
            if dep not in by_id:
                raise ValidationError(f"unknown dependency {dep}")
    # Iterative topological validation avoids recursion limits on external input.
    incoming = {sid: len(s.get("dependencies", [])) for sid, s in by_id.items()}
    children = {sid: [] for sid in by_id}
    for sid, step in by_id.items():
        for dep in step.get("dependencies", []):
            children[dep].append(sid)
    stack = [sid for sid, n in incoming.items() if n == 0]
    visited = 0
    while stack:
        sid = stack.pop()
        visited += 1
        for child in children[sid]:
            incoming[child] -= 1
            if incoming[child] == 0:
                stack.append(child)
    if visited != len(steps):
        raise ValidationError("dependency graph contains a cycle")
    values = q.get("t")
    evidence = q.get("T_evidence")
    if not isinstance(values, list) or len(values) != 5:
        raise ValidationError("t must contain five values; unknown is not zero")
    if not isinstance(evidence, list) or len(evidence) != 5:
        raise ValidationError("T_evidence must contain five evidence objects")
    for i, (value, item) in enumerate(zip(values, evidence), 1):
        _integer(value, 0, 2, f"t[{i}]")
        if not isinstance(item, dict):
            raise ValidationError("T evidence item must be an object")
        _text(item.get("evidence"), f"T evidence {i}")
        if item.get("item", i) != i or item.get("value", value) != value:
            raise ValidationError("T evidence index/value does not match t")
    _integer(q.get("B"), 0, 3, "B")
    _text(q.get("B_evidence"), "B_evidence")
    branches = q.get("branches", 0)
    if type(branches) is not int or branches < 0:
        raise ValidationError("branches must be a non-negative integer")
    if q.get("score") is not None:
        mark = q["score"]
        if type(mark) not in (int, float) or not isfinite(mark) or mark <= 0:
            raise ValidationError("score must be positive or null")


def score_question(q, *, max_paths=100_000):
    """Recompute all scores, ignoring historical H/C/T/D/s/path fields.

    A pending question returns null scores. max_paths bounds graph expansion;
    an oversized graph fails explicitly rather than guessing a path.
    """
    _validate(q)
    if type(max_paths) is not int or max_paths < 1:
        raise ValidationError("max_paths must be a positive integer")
    identity = {k: q[k] for k in ("id", "year", "module", "question", "score") if k in q}
    if q.get("pending"):
        return {**identity, "pending": True, "issue": q["issue"],
                **{k: None for k in ("H", "C", "T", "D", "B", "E", "peak")},
                "band": "待复核", "path": [], "step_scores": []}
    with localcontext() as context:
        context.prec = 40
        by_id = {s["id"]: s for s in q["steps"]}
        loads = {sid: sum(w * step["dimensions"][k] / 2
                         for k, w in zip(DIMENSIONS, WEIGHTS))
                 for sid, step in by_id.items()}
        used = {dep for s in by_id.values() for dep in s.get("dependencies", [])}
        terminals = [sid for sid in by_id if sid not in used]
        best, best_path, best_detail = Decimal(-1), None, None
        count = 0
        expanded = 0
        stack = [(sid, [sid]) for sid in terminals]
        while stack:
            expanded += 1
            if expanded > max_paths * max(len(by_id), 1):
                raise ValidationError("dependency graph expansion exceeds limit")
            sid, reverse_path = stack.pop()
            deps = by_id[sid].get("dependencies", [])
            if deps:
                stack.extend((dep, reverse_path + [dep]) for dep in deps)
                continue
            count += 1
            if count > max_paths:
                raise ValidationError("too many dependency paths; simplify graph or increase max_paths")
            path = list(reversed(reverse_path))
            groups, detail, load = {}, [], Decimal(0)
            for index, current in enumerate(path):
                group = by_id[current].get("repeat_group")
                if group is None:
                    repeat = Decimal(1)
                else:
                    groups[group] = groups.get(group, 0) + 1
                    repeat = (Decimal(1), Decimal(".7"), Decimal(".4"))[min(groups[group], 3)-1]
                depth = min(Decimal(1) + Decimal(".1") * index, Decimal("1.3"))
                effective = loads[current] * repeat * depth
                load += effective
                detail.append(dict(id=current, s=float(loads[current]), r=float(repeat),
                                   d=float(depth), e=float(effective)))
            # Stable tie-breaker: lexicographically smallest path.
            if load > best or (load == best and tuple(path) < tuple(best_path)):
                best, best_path, best_detail = load, path, detail
        H = rounded(100 * max(loads.values()))
        C = rounded(100 * (1 - (-best / 3).exp()))
        T = 10 * sum(q["t"])
        D = rounded(Decimal(".45")*H + Decimal(".35")*C + Decimal(".20")*T)
    return {**identity, "pending": False, "H": H, "C": C, "T": T, "D": D,
            "B": q["B"], "band": "基础" if D < 35 else "中档" if D < 65 else "难题",
            "E": float(best), "path": best_detail,
            "step_scores": [{"id": sid, "s": float(v)} for sid, v in loads.items()],
            "peak": {k: max(s["dimensions"][k] for s in by_id.values()) for k in DIMENSIONS},
            "branches": q.get("branches", 0),
            "review_flag": (D < 35 and q["B"] >= 2) or q.get("branches", 0) >= 3}


def score_paper(questions):
    """Return question results and statistics with explicit denominators.

    Weighted whole-paper mean is emitted only when every question's mark and
    score are known. Known-mark subset statistics are separately labeled.
    """
    if not isinstance(questions, list) or not questions:
        raise ValidationError("questions must be a non-empty list")
    results = [score_question(q) for q in questions]
    keys = [(r.get("year"), r["id"]) for r in results]
    if len(set(keys)) != len(keys):
        raise ValidationError("duplicate question IDs within a paper/year")
    valid = [r for r in results if r["D"] is not None]
    ds = [r["D"] for r in valid]
    known = [r for r in results if r.get("score") is not None]
    known_valid = [r for r in known if r["D"] is not None]
    # Validate pending-question marks too, since they affect the denominator.
    for r in known:
        mark = r["score"]
        if type(mark) not in (int, float) or not isfinite(mark) or mark <= 0:
            raise ValidationError("score must be positive or null")
    total_known = sum(r["score"] for r in known)
    valid_known = sum(r["score"] for r in known_valid)
    weighted_subset = sum(r["score"]*r["D"] for r in known_valid)/valid_known if valid_known else None
    complete = len(known_valid) == len(results)
    stats = dict(total=len(results), valid=len(valid), pending=len(results)-len(valid),
                 coverage=len(valid)/len(results), mean=mean(ds) if ds else None,
                 median=median(ds) if ds else None, maximum=max(ds) if ds else None,
                 population_sd=pstdev(ds) if ds else None,
                 mean_scope="全部小问等权" if len(valid)==len(results) else "已分析部分小问等权",
                 bands={b: sum(r["band"]==b for r in valid) for b in ("基础","中档","难题")},
                 known_points=total_known, valid_known_points=valid_known,
                 known_points_coverage=valid_known/total_known if total_known else None,
                 known_points_weighted_mean=weighted_subset,
                 whole_paper_weighted_mean=weighted_subset if complete else None,
                 weighted_scope="整卷分值已知且全部定分" if complete else "只可报告分值明确且已定分的子集",
                 mean_HCT={k:mean(r[k] for r in valid) if valid else None for k in "HCT"},
                 peak_profile={k:mean(r["peak"][k] for r in valid) if valid else None for k in DIMENSIONS})
    return {"algorithm": "HCT-rules-v1.1", "engine": "0.1.0", "statistics": stats, "questions": results}
