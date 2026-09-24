import argparse
import copy
import json
import sys
from pathlib import Path
from .engine import score_question, score_paper, ValidationError


def score_input(data, scope="auto"):
    """Select report scope without changing the scoring rules."""
    if not isinstance(data, dict):
        raise ValidationError("input must be an object")
    if scope not in ("auto", "question", "paper"):
        raise ValidationError("unknown scope")
    if "questions" not in data:
        if scope == "paper":
            raise ValidationError("paper scope requires a questions array")
        return {"algorithm": "HCT-rules-v1.1", "engine": "0.1.1",
                "scope": "question", "question": score_question(data)}
    if "steps" in data:
        raise ValidationError("ambiguous input: both steps and questions")
    selected = data.get("scope", "paper") if scope == "auto" else scope
    if selected not in ("question", "paper"):
        raise ValidationError("scope must be question or paper")
    result = score_paper(data["questions"])
    if selected == "question":
        stats = result["statistics"]
        stats["whole_question_weighted_mean"] = stats.pop("whole_paper_weighted_mean")
        stats["weighted_scope"] = stats["weighted_scope"].replace("整卷", "整题")
    result["scope"] = selected
    return result


def _fill_and_score_with_suggestions(data, scope, config, verbose=True):
    """Fill missing labels with Jev suggestions, then score.
    
    Args:
        data: Input data (question or questions array).
        scope: Scoring scope.
        config: SuggestionConfig for Jev.
        verbose: Print progress to stderr.
    
    Returns:
        Tuple of (filled_data, scored_result).
        filled_data has Jev suggestions applied.
        scored_result is from score_input on filled_data.
    """
    from .jev_suggest import (
        suggest_question_labels, apply_suggestions_to_question,
        format_suggestion_summary
    )
    
    # Deep copy to avoid modifying original
    filled_data = copy.deepcopy(data)
    
    # Get questions to suggest labels for
    if "questions" in filled_data:
        questions = filled_data["questions"]
    else:
        questions = [filled_data]
    
    if verbose:
        print(f"正在为 {len(questions)} 个问题请求Jev标签建议并填充...", file=sys.stderr)
    
    filled_count = 0
    for i, q in enumerate(questions):
        if q.get("pending"):
            if verbose:
                print(f"  跳过待复核问题: {q.get('id', i+1)}", file=sys.stderr)
            continue
        
        if verbose:
            print(f"  处理问题 {q.get('id', i+1)}...", file=sys.stderr)
        
        suggestion = suggest_question_labels(q, config)
        
        if suggestion:
            # Apply suggestions to fill missing fields
            filled_q = apply_suggestions_to_question(q, suggestion, config)
            
            # Replace the question in the list/data
            if "questions" in filled_data:
                filled_data["questions"][i] = filled_q
            else:
                filled_data = filled_q
            
            filled_count += 1
            
            if verbose:
                meta = filled_q.get("jev_meta", {})
                filled = meta.get("filled_fields", [])
                preserved = len(meta.get("preserved_human_labels", []))
                disagreements = len(meta.get("disagreements", []))
                print(f"    填充了 {len(filled)} 个字段", file=sys.stderr)
                if preserved:
                    print(f"    保留了 {preserved} 个人工标签", file=sys.stderr)
                if disagreements:
                    print(f"    发现 {disagreements} 处分歧（已记录在jev_meta中）", file=sys.stderr)
                if filled_q.get("jev_needs_review"):
                    reasons = filled_q.get("jev_review_reasons", [])
                    print(f"    需要复核: {len(reasons)} 个原因", file=sys.stderr)
    
    if verbose:
        print(f"完成，共处理 {filled_count} 个问题", file=sys.stderr)
        print("", file=sys.stderr)
    
    # Score the filled data using unchanged engine
    result = score_input(filled_data, scope)
    
    # Propagate Jev markers to the scored result
    if "questions" in filled_data:
        for i, q in enumerate(filled_data["questions"]):
            if "jev_labels_pending" in q:
                result["questions"][i]["jev_labels_pending"] = q["jev_labels_pending"]
            if "jev_needs_review" in q:
                result["questions"][i]["jev_needs_review"] = q["jev_needs_review"]
            if "jev_review_reasons" in q:
                result["questions"][i]["jev_review_reasons"] = q["jev_review_reasons"]
            if "jev_meta" in q:
                result["questions"][i]["jev_meta"] = q["jev_meta"]
    elif "question" in result:
        if "jev_labels_pending" in filled_data:
            result["question"]["jev_labels_pending"] = filled_data["jev_labels_pending"]
        if "jev_needs_review" in filled_data:
            result["question"]["jev_needs_review"] = filled_data["jev_needs_review"]
        if "jev_review_reasons" in filled_data:
            result["question"]["jev_review_reasons"] = filled_data["jev_review_reasons"]
        if "jev_meta" in filled_data:
            result["question"]["jev_meta"] = filled_data["jev_meta"]
    
    return filled_data, result


def main():
    parser = argparse.ArgumentParser(description="复算有依据的H/C/T/D规则分；不自动解题或预测得分率。")
    parser.add_argument("input", type=Path, help="单小问对象，或含questions数组的JSON文件")
    parser.add_argument("--scope", choices=("auto", "question", "paper"), default="auto",
                        help="分析范围；多小问单题可设question；旧数组默认paper")
    parser.add_argument("--output", type=Path, help="结果JSON；省略则输出到终端")
    parser.add_argument("--suggest-labels", action="store_true",
                        help="使用Jev填充缺失的K/R/A/V/P/I、T、B标签后评分（需typesafe-sdk和TYPESAFE_API_KEY）")
    parser.add_argument("--draft-output", type=Path,
                        help="保存填充后的草稿JSON，供教师编辑标签后重新评分")
    parser.add_argument("--confidence-threshold", type=float, default=0.6,
                        help="Jev建议的置信度阈值（默认0.6）")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8-sig"))
        
        # Handle --suggest-labels
        if args.suggest_labels:
            try:
                from .jev_suggest import is_available, SuggestionConfig
            except ImportError:
                print("错误：typesafe-sdk未安装。请运行: pip install question-difficulty-analysis[typesafe]", file=sys.stderr)
                return 2
            
            available, msg = is_available()
            if not available:
                print(f"Jev建议不可用：{msg}", file=sys.stderr)
                return 2
            
            config = SuggestionConfig(confidence_threshold=args.confidence_threshold)
            
            # Fill missing labels and score
            filled_data, result = _fill_and_score_with_suggestions(
                data, args.scope, config, verbose=True
            )
            
            # Optionally save the filled draft
            if args.draft_output:
                if args.draft_output.resolve() == args.input.resolve():
                    raise ValidationError("draft-output must not overwrite the input")
                args.draft_output.parent.mkdir(parents=True, exist_ok=True)
                
                # For draft, wrap single question in proper format for re-running
                if "questions" not in data:
                    draft_data = filled_data
                else:
                    draft_data = filled_data
                
                draft_text = json.dumps(draft_data, ensure_ascii=False, indent=2, allow_nan=False)
                args.draft_output.write_text(draft_text + "\n", encoding="utf-8")
                print(f"草稿已保存到 {args.draft_output}", file=sys.stderr)
                print("教师可编辑标签后运行: python -m question_difficulty <draft.json> --output <result.json>", file=sys.stderr)
        else:
            # Default behavior: score without suggestions
            result = score_input(data, args.scope)
        
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            if args.output.resolve() == args.input.resolve():
                raise ValidationError("output must not overwrite the input evidence")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text+"\n", encoding="utf-8")
        else:
            print(text)
    except (OSError, ValueError, TypeError) as exc:
        print(f"输入或计算错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
