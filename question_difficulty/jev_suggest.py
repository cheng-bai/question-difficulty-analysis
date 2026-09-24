"""Optional TypeSafe (Jev) helper for suggesting semantic labels.

This module provides AI-assisted suggestions for the dimension scores,
T risk items, and breakthrough levels that the scoring engine expects.
All suggestions require human confirmation before use.

Requires: pip install question-difficulty-analysis[typesafe]
Environment: TYPESAFE_API_KEY must be set.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

DIMENSIONS = "KRAVPI"

# Chinese rubric definitions from the prompt (通用提示词)
DIMENSION_CRITERIA = {
    "K": {
        "name": "知识与方法识别",
        "levels": {
            0: "题面直接对应公式、定义或定理",
            1: "需完成可明确指出的标准变式转换",
            2: "需识别未显露的关系或非常规方法组合",
        },
    },
    "R": {
        "name": "条件转换与推理",
        "levels": {
            0: "单步直接推得",
            1: "两三次常见转换",
            2: "隐含条件、逆向构造或长依赖",
        },
    },
    "A": {
        "name": "代数运算负荷",
        "levels": {
            0: "一两步常规运算",
            1: "中等化简或联立",
            2: "长符号链、复杂含参运算或高错误敏感计算",
        },
    },
    "V": {
        "name": "表征转换",
        "levels": {
            0: "不需要",
            1: "一次文字、图像、公式、坐标转换",
            2: "多次或双向转换",
        },
    },
    "P": {
        "name": "参数、新定义与边界",
        "levels": {
            0: "无额外负担",
            1: "单一参数、规则解读或边界",
            2: "多分支、复杂量词或相互制约的边界",
        },
    },
    "I": {
        "name": "知识交汇",
        "levels": {
            0: "单模块",
            1: "两模块浅层配合",
            2: "不同模块在同一关键推理中深度耦合",
        },
    },
}

T_CRITERIA = {
    1: {
        "name": "正确入口的隐蔽程度",
        "levels": {
            0: "入口直接显露，无需额外识别",
            1: "入口需要有限的条件识别或标准转换",
            2: "入口隐蔽，需要非显然的洞察或尝试",
        },
    },
    2: {
        "name": "多个看似合理但无效的入口",
        "levels": {
            0: "没有竞争的无效入口",
            1: "存在一两个看似合理但会失败的方向",
            2: "存在多个诱人但无效的方向，显著增加试错成本",
        },
    },
    3: {
        "name": "错误多久以后才能被发现",
        "levels": {
            0: "错误能立即被发现（下一步或代入即见）",
            1: "错误需要若干步后才能发现",
            2: "错误可能到最后才发现，或难以定位",
        },
    },
    4: {
        "name": "发现错误后需要回退的范围",
        "levels": {
            0: "回退代价很小，只需修改局部",
            1: "需要回退中等范围的工作",
            2: "需要大幅回退或几乎重做",
        },
    },
    5: {
        "name": "端点、等号或退化遗漏造成的风险",
        "levels": {
            0: "没有边界条件需要特别检查",
            1: "存在需要检查的端点或等号情形",
            2: "存在多个容易遗漏的边界或退化情形",
        },
    },
}

B_CRITERIA = {
    0: "直接识别：题干条件直接提示方法，无需额外发现",
    1: "常见方法组合：需要组合已知方法，但组合方式是标准的",
    2: "需要非显然的转化或构造：关键一步不是显然的，需要一定洞察",
    3: "缺少显性提示，独立发现存在明显门槛：关键突破需要非凡的洞察或创造性",
}


@dataclass
class SuggestionConfig:
    """Configuration for Jev suggestion behavior."""
    
    model: str = "jev-1.13"
    confidence_threshold: float = 0.6
    low_confidence_threshold: float = 0.4
    mark_low_confidence_review: bool = True
    parallel_steps: int = 5


@dataclass
class DimensionSuggestion:
    """Suggestion for a single dimension score."""
    
    value: int
    confidence: float
    probabilities: dict[int, float]


@dataclass
class StepSuggestion:
    """Suggestions for all dimensions of one step."""
    
    step_id: str
    dimensions: dict[str, DimensionSuggestion]
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)


@dataclass
class TSuggestion:
    """Suggestion for T risk items."""
    
    values: list[int]
    items: list[dict[str, Any]]
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)


@dataclass
class BSuggestion:
    """Suggestion for breakthrough level."""
    
    value: int
    confidence: float
    probabilities: dict[int, float]
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)


@dataclass
class QuestionSuggestion:
    """Complete suggestion for a question."""
    
    step_suggestions: list[StepSuggestion]
    t_suggestion: TSuggestion
    b_suggestion: BSuggestion
    has_ambiguity: bool = False
    ambiguity_note: str = ""
    jev_meta: dict[str, Any] = field(default_factory=dict)


def _check_sdk_available() -> bool:
    """Check if typesafe-sdk is available."""
    try:
        import typesafe_sdk  # noqa: F401
        return True
    except ImportError:
        return False


def _check_api_key() -> bool:
    """Check if TYPESAFE_API_KEY is set."""
    return bool(os.environ.get("TYPESAFE_API_KEY"))


def is_available() -> tuple[bool, str]:
    """Check if Jev suggestions are available.
    
    Returns:
        Tuple of (available, message).
    """
    if not _check_sdk_available():
        return False, "typesafe-sdk not installed. Install with: pip install question-difficulty-analysis[typesafe]"
    if not _check_api_key():
        return False, "TYPESAFE_API_KEY not set in environment"
    return True, "Jev suggestions available"


def _build_step_state(step: dict, question_context: dict) -> dict:
    """Build state for step dimension evaluation.
    
    Uses honest field names:
    - `question_text`: actual problem stem if provided, otherwise empty
    - `final_answer`: the final answer to the question
    - `module`: math module/topic
    - `stages`: target stages if available
    """
    state = {
        "context": {
            "module": question_context.get("module", ""),
            "final_answer": question_context.get("final_answer", ""),
        },
        "step": {
            "id": step.get("id", ""),
            "input": step.get("input", ""),
            "action": step.get("action", ""),
            "output": step.get("output", ""),
            "type_id": step.get("type_id", ""),
        },
        "dependencies": {
            "count": len(step.get("dependencies", [])),
            "ids": step.get("dependencies", []),
        },
    }
    
    # Include optional fields only if present
    if question_context.get("question_text"):
        state["context"]["question_text"] = question_context["question_text"]
    if question_context.get("stages"):
        state["context"]["stages"] = question_context["stages"]
    if question_context.get("knowledge_tags"):
        state["context"]["knowledge_tags"] = question_context["knowledge_tags"]
    
    return state


def _build_dimension_questions(has_question_text: bool) -> dict:
    """Build Choice questions for all six dimensions.
    
    Args:
        has_question_text: Whether the state includes question_text (stem).
    """
    from typesafe_sdk import Choice
    
    context_note = (
        "参考 `context.question_text`（题干）、`context.module`（模块）和 `context.final_answer`（最终答案）。"
        if has_question_text else
        "参考 `context.module`（模块）和 `context.final_answer`（最终答案）；无题干文本，仅依据步骤内容评分。"
    )
    
    questions = {}
    for dim, criteria in DIMENSION_CRITERIA.items():
        questions[dim] = Choice(
            instructions={
                "question": f"根据 `step` 中的数学动作，{criteria['name']}({dim})应该得几分？",
                "context": context_note,
                "focus": "只评价 `step.action` 的实际数学动作，不因题干含特定词汇给所有步骤重复加分。",
                "rubric": criteria["name"],
            },
            criteria={
                "0": criteria["levels"][0],
                "1": criteria["levels"][1],
                "2": criteria["levels"][2],
            },
        )
    return questions


def _suggest_step_dimensions(
    step: dict,
    question_context: dict,
    client: Any,
    config: SuggestionConfig,
) -> StepSuggestion:
    """Suggest dimension scores for a single step."""
    state = _build_step_state(step, question_context)
    has_question_text = bool(question_context.get("question_text"))
    questions = _build_dimension_questions(has_question_text)
    
    response = client.system_one(
        state=state,
        questions=questions,
        model=config.model,
    )
    
    dimensions = {}
    needs_review = False
    review_reasons = []
    
    # Mark for review if no question text provided (low-context evaluation)
    if not has_question_text:
        needs_review = True
        review_reasons.append("no question_text (stem) provided; evaluation based on step content only")
    
    for dim in DIMENSIONS:
        answer = response.choices[dim]
        value = int(answer.choice)
        confidence = answer.confidence
        probs = {int(k): v for k, v in answer.probabilities.items()}
        
        dimensions[dim] = DimensionSuggestion(
            value=value,
            confidence=confidence,
            probabilities=probs,
        )
        
        if confidence < config.low_confidence_threshold:
            needs_review = True
            review_reasons.append(f"{dim} confidence {confidence:.2f} below threshold")
    
    return StepSuggestion(
        step_id=step.get("id", ""),
        dimensions=dimensions,
        needs_review=needs_review,
        review_reasons=review_reasons,
    )


def _build_t_questions(has_question_text: bool) -> dict:
    """Build Choice questions for T risk items.
    
    Args:
        has_question_text: Whether the state includes question_text (stem).
    """
    from typesafe_sdk import Choice
    
    context_note = (
        "参考 `question.question_text`（题干）、`question.module` 和 `steps_summary`。"
        if has_question_text else
        "参考 `question.module`、`question.final_answer` 和 `steps_summary`；无题干文本。"
    )
    
    questions = {}
    for i, criteria in T_CRITERIA.items():
        questions[f"t{i}"] = Choice(
            instructions={
                "question": f"T风险第{i}项：{criteria['name']}，风险程度如何？",
                "context": context_note,
                "focus": "评估路径结构风险，不因计算较长直接加分。",
            },
            criteria={
                "0": criteria["levels"][0],
                "1": criteria["levels"][1],
                "2": criteria["levels"][2],
            },
        )
    return questions


def _build_b_question(has_question_text: bool) -> dict:
    """Build Choice question for breakthrough level.
    
    Args:
        has_question_text: Whether the state includes question_text (stem).
    """
    from typesafe_sdk import Choice
    
    context_note = (
        "参考 `question.question_text`（题干）中的提示程度和 `steps_summary` 中需要跨越的障碍。"
        if has_question_text else
        "参考 `question.module`、`question.final_answer` 和 `steps_summary`；无题干文本，仅依据步骤推断。"
    )
    
    return {
        "B": Choice(
            instructions={
                "question": "这道题的关键突破难度(B)是多少？",
                "context": context_note,
                "focus": "评估独立发现关键一步的难度，不是整体计算量。",
            },
            criteria={
                "0": B_CRITERIA[0],
                "1": B_CRITERIA[1],
                "2": B_CRITERIA[2],
                "3": B_CRITERIA[3],
            },
        )
    }


def _build_ambiguity_question(has_question_text: bool) -> dict:
    """Build Noul question for material ambiguity check.
    
    Args:
        has_question_text: Whether the state includes question_text (stem).
    """
    from typesafe_sdk import Noul, NoulCriteria
    
    if has_question_text:
        instructions = {
            "question": "材料是否存在歧义、版本冲突或缺失图形等影响评分的问题？",
            "focus": "检查 `question.question_text`、`question.final_answer` 和 `steps_summary` 中可能导致评分不可靠的问题。",
        }
    else:
        instructions = {
            "question": "仅依据步骤信息，材料是否存在歧义或缺失？",
            "focus": "注意：无题干文本(`question_text`)；仅检查 `steps_summary` 中可能的问题。",
            "note": "缺少题干本身会限制评分可靠性，但这里仅检测步骤内容中的歧义。",
        }
    
    return {
        "has_ambiguity": Noul(
            instructions=instructions,
            criteria=NoulCriteria(
                true={
                    "what": "存在影响评分的歧义或缺失",
                    "examples": ["缺少关键图形", "条件有多种理解方式", "答案与解析不一致", "步骤引用了未给出的条件"],
                },
                false={
                    "what": "给定材料完整清晰，可以在当前信息下评分",
                },
            ),
        )
    }


def _build_question_state(question: dict) -> tuple[dict, bool]:
    """Build state for question-level evaluation (T, B, ambiguity).
    
    Returns:
        Tuple of (state dict, has_question_text flag).
    """
    steps_summary = []
    for step in question.get("steps", []):
        steps_summary.append({
            "id": step.get("id", ""),
            "action": step.get("action", ""),
            "dependencies": step.get("dependencies", []),
        })
    
    # Check for optional question_text/stem field
    question_text = question.get("question_text") or question.get("stem") or ""
    has_question_text = bool(question_text)
    
    state = {
        "question": {
            "id": question.get("id", ""),
            "module": question.get("module", ""),
            "final_answer": question.get("answer", ""),
        },
        "steps_summary": steps_summary,
        "step_count": len(steps_summary),
    }
    
    # Include optional fields only if present
    if has_question_text:
        state["question"]["question_text"] = question_text
    if question.get("stages"):
        state["question"]["stages"] = question["stages"]
    if question.get("target_stages"):
        state["question"]["target_stages"] = question["target_stages"]
    
    return state, has_question_text


def _suggest_t_and_b(
    question: dict,
    client: Any,
    config: SuggestionConfig,
) -> tuple[TSuggestion, BSuggestion, bool, str, bool]:
    """Suggest T risk items, B breakthrough level, and check for ambiguity.
    
    Returns:
        Tuple of (t_suggestion, b_suggestion, has_ambiguity, ambiguity_note, has_question_text).
    """
    state, has_question_text = _build_question_state(question)
    
    questions = {}
    questions.update(_build_t_questions(has_question_text))
    questions.update(_build_b_question(has_question_text))
    questions.update(_build_ambiguity_question(has_question_text))
    
    response = client.system_one(
        state=state,
        questions=questions,
        model=config.model,
    )
    
    # Process T items
    t_values = []
    t_items = []
    t_needs_review = False
    t_review_reasons = []
    
    # Mark for review if no question text provided
    if not has_question_text:
        t_needs_review = True
        t_review_reasons.append("no question_text (stem) provided; T evaluation based on steps only")
    
    for i in range(1, 6):
        answer = response.choices[f"t{i}"]
        value = int(answer.choice)
        confidence = answer.confidence
        t_values.append(value)
        
        t_items.append({
            "item": i,
            "value": value,
            "confidence": confidence,
            "probabilities": {int(k): v for k, v in answer.probabilities.items()},
            "evidence": f"[Jev建议，待教师确认] {T_CRITERIA[i]['name']}: {T_CRITERIA[i]['levels'][value]}",
        })
        
        if confidence < config.low_confidence_threshold:
            t_needs_review = True
            t_review_reasons.append(f"t{i} confidence {confidence:.2f} below threshold")
    
    t_suggestion = TSuggestion(
        values=t_values,
        items=t_items,
        needs_review=t_needs_review,
        review_reasons=t_review_reasons,
    )
    
    # Process B
    b_answer = response.choices["B"]
    b_value = int(b_answer.choice)
    b_confidence = b_answer.confidence
    b_probs = {int(k): v for k, v in b_answer.probabilities.items()}
    
    b_needs_review = b_confidence < config.low_confidence_threshold
    b_review_reasons = []
    
    # Mark for review if no question text provided
    if not has_question_text:
        b_needs_review = True
        b_review_reasons.append("no question_text (stem) provided; B evaluation based on steps only")
    
    if b_confidence < config.low_confidence_threshold:
        b_review_reasons.append(f"B confidence {b_confidence:.2f} below threshold")
    
    b_suggestion = BSuggestion(
        value=b_value,
        confidence=b_confidence,
        probabilities=b_probs,
        needs_review=b_needs_review,
        review_reasons=b_review_reasons,
    )
    
    # Process ambiguity
    ambiguity_prob = response.nouls["has_ambiguity"].noul
    has_ambiguity = ambiguity_prob > 0.5
    ambiguity_note = ""
    if has_ambiguity:
        ambiguity_note = f"[Jev检测到潜在问题，概率{ambiguity_prob:.2f}] 材料可能存在歧义、版本冲突或缺失图形，建议人工复核后再确定评分。"
    
    return t_suggestion, b_suggestion, has_ambiguity, ambiguity_note, has_question_text


def suggest_question_labels(
    question: dict,
    config: SuggestionConfig | None = None,
) -> QuestionSuggestion | None:
    """Suggest labels for a question using Jev.
    
    Args:
        question: Question dict with steps, id, module, answer fields.
            Optional fields:
            - question_text or stem: actual problem text (if available)
            - stages or target_stages: goal stages (if available)
        config: Configuration for suggestion behavior.
    
    Returns:
        QuestionSuggestion with all suggested labels and metadata,
        or None if Jev is not available.
    
    Note:
        When no question_text/stem is provided, suggestions are marked
        needs_review since evaluation is based only on step content.
    """
    available, msg = is_available()
    if not available:
        return None
    
    if config is None:
        config = SuggestionConfig()
    
    from typesafe_sdk import TypeSafeClient
    
    # Build question context for step evaluation with honest field names
    # Use question_text or stem if provided; otherwise leave empty
    question_text = question.get("question_text") or question.get("stem") or ""
    
    question_context = {
        "final_answer": question.get("answer", ""),
        "module": question.get("module", ""),
    }
    
    # Include optional fields only if present
    if question_text:
        question_context["question_text"] = question_text
    if question.get("stages"):
        question_context["stages"] = question["stages"]
    if question.get("target_stages"):
        question_context["stages"] = question["target_stages"]
    
    step_suggestions = []
    jev_meta: dict[str, Any] = {
        "model": config.model,
        "confidence_threshold": config.confidence_threshold,
        "low_confidence_threshold": config.low_confidence_threshold,
        "has_question_text": bool(question_text),
    }
    
    with TypeSafeClient() as client:
        # Suggest dimensions for each step
        steps = question.get("steps", [])
        for step in steps:
            step_suggestion = _suggest_step_dimensions(
                step, question_context, client, config
            )
            step_suggestions.append(step_suggestion)
        
        # Suggest T, B, and check ambiguity
        t_suggestion, b_suggestion, has_ambiguity, ambiguity_note, has_question_text = _suggest_t_and_b(
            question, client, config
        )
    
    # Record raw data in metadata
    jev_meta["step_details"] = [
        {
            "step_id": s.step_id,
            "dimensions": {
                dim: {
                    "value": d.value,
                    "confidence": d.confidence,
                    "probabilities": d.probabilities,
                }
                for dim, d in s.dimensions.items()
            },
            "needs_review": s.needs_review,
            "review_reasons": s.review_reasons,
        }
        for s in step_suggestions
    ]
    jev_meta["t_details"] = {
        "values": t_suggestion.values,
        "items": t_suggestion.items,
        "needs_review": t_suggestion.needs_review,
        "review_reasons": t_suggestion.review_reasons,
    }
    jev_meta["b_details"] = {
        "value": b_suggestion.value,
        "confidence": b_suggestion.confidence,
        "probabilities": b_suggestion.probabilities,
        "needs_review": b_suggestion.needs_review,
        "review_reasons": b_suggestion.review_reasons,
    }
    jev_meta["ambiguity"] = {
        "detected": has_ambiguity,
        "note": ambiguity_note,
    }
    
    return QuestionSuggestion(
        step_suggestions=step_suggestions,
        t_suggestion=t_suggestion,
        b_suggestion=b_suggestion,
        has_ambiguity=has_ambiguity,
        ambiguity_note=ambiguity_note,
        jev_meta=jev_meta,
    )


def apply_suggestions_to_question(
    question: dict,
    suggestion: QuestionSuggestion,
    config: SuggestionConfig | None = None,
    overwrite_existing: bool = False,
) -> dict:
    """Apply Jev suggestions to a question dict.
    
    Only applies suggestions that meet confidence thresholds.
    Low-confidence suggestions are skipped and marked for review.
    Existing human labels are preserved unless overwrite_existing=True.
    
    Args:
        question: Original question dict.
        suggestion: QuestionSuggestion from suggest_question_labels.
        config: Configuration for confidence thresholds.
        overwrite_existing: If True, overwrite existing labels.
    
    Returns:
        Modified question dict with suggested labels applied.
    """
    if config is None:
        config = SuggestionConfig()
    
    import copy
    result = copy.deepcopy(question)
    
    # Apply step dimension suggestions
    steps_by_id = {s["id"]: s for s in result.get("steps", [])}
    
    for step_suggestion in suggestion.step_suggestions:
        step = steps_by_id.get(step_suggestion.step_id)
        if step is None:
            continue
        
        if "dimensions" not in step:
            step["dimensions"] = {}
        if "dimension_evidence" not in step:
            step["dimension_evidence"] = {}
        
        for dim, dim_suggestion in step_suggestion.dimensions.items():
            has_existing = (
                dim in step["dimensions"]
                and step["dimensions"][dim] is not None
            )
            
            if has_existing and not overwrite_existing:
                continue
            
            if dim_suggestion.confidence < config.confidence_threshold:
                if config.mark_low_confidence_review:
                    step["dimension_evidence"][dim] = (
                        f"[Jev建议待复核，置信度{dim_suggestion.confidence:.2f}] "
                        f"建议值{dim_suggestion.value}，概率分布{dim_suggestion.probabilities}"
                    )
                continue
            
            step["dimensions"][dim] = dim_suggestion.value
            step["dimension_evidence"][dim] = (
                f"[Jev建议，置信度{dim_suggestion.confidence:.2f}，待教师确认] "
                f"{DIMENSION_CRITERIA[dim]['levels'][dim_suggestion.value]}"
            )
    
    # Apply T suggestions
    has_existing_t = (
        "t" in result
        and isinstance(result["t"], list)
        and any(v is not None for v in result["t"])
    )
    
    if not has_existing_t or overwrite_existing:
        all_t_confident = all(
            item["confidence"] >= config.confidence_threshold
            for item in suggestion.t_suggestion.items
        )
        
        if all_t_confident or not has_existing_t:
            result["t"] = suggestion.t_suggestion.values
            result["T_evidence"] = [
                {
                    "item": item["item"],
                    "value": item["value"],
                    "evidence": item["evidence"],
                }
                for item in suggestion.t_suggestion.items
            ]
    
    # Apply B suggestion
    has_existing_b = "B" in result and result["B"] is not None
    
    if not has_existing_b or overwrite_existing:
        if suggestion.b_suggestion.confidence >= config.confidence_threshold:
            result["B"] = suggestion.b_suggestion.value
            result["B_evidence"] = (
                f"[Jev建议，置信度{suggestion.b_suggestion.confidence:.2f}，待教师确认] "
                f"{B_CRITERIA[suggestion.b_suggestion.value]}"
            )
    
    # Add review flag if any low confidence
    any_needs_review = (
        any(s.needs_review for s in suggestion.step_suggestions)
        or suggestion.t_suggestion.needs_review
        or suggestion.b_suggestion.needs_review
        or suggestion.has_ambiguity
    )
    
    if any_needs_review:
        result["jev_needs_review"] = True
        review_reasons = []
        for s in suggestion.step_suggestions:
            review_reasons.extend(s.review_reasons)
        review_reasons.extend(suggestion.t_suggestion.review_reasons)
        review_reasons.extend(suggestion.b_suggestion.review_reasons)
        if suggestion.has_ambiguity:
            review_reasons.append(suggestion.ambiguity_note)
        result["jev_review_reasons"] = review_reasons
    
    # Store metadata
    result["jev_meta"] = suggestion.jev_meta
    
    return result


def format_suggestion_summary(suggestion: QuestionSuggestion) -> str:
    """Format a human-readable summary of suggestions."""
    lines = ["=== Jev 标签建议 (待教师确认) ===", ""]
    
    # Step dimensions
    lines.append("步骤维度建议：")
    for step_s in suggestion.step_suggestions:
        dims = " ".join(
            f"{d}={s.value}({s.confidence:.2f})"
            for d, s in step_s.dimensions.items()
        )
        review_mark = " [需复核]" if step_s.needs_review else ""
        lines.append(f"  {step_s.step_id}: {dims}{review_mark}")
    
    lines.append("")
    
    # T items
    lines.append("T 风险项建议：")
    for item in suggestion.t_suggestion.items:
        lines.append(
            f"  t{item['item']}={item['value']} "
            f"({item['confidence']:.2f})"
        )
    if suggestion.t_suggestion.needs_review:
        lines.append("  [T项需复核]")
    
    lines.append("")
    
    # B
    lines.append(
        f"B 突破难度建议：{suggestion.b_suggestion.value} "
        f"(置信度 {suggestion.b_suggestion.confidence:.2f})"
    )
    if suggestion.b_suggestion.needs_review:
        lines.append("  [B需复核]")
    
    # Ambiguity
    if suggestion.has_ambiguity:
        lines.append("")
        lines.append(f"⚠️ {suggestion.ambiguity_note}")
    
    lines.append("")
    lines.append("注意：所有建议均需教师确认后方可使用。")
    lines.append("TypeSafe文档指出非英文文本准确率较低，建议在上海案例上调参后使用。")
    
    return "\n".join(lines)
