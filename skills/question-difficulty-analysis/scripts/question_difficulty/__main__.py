import argparse
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


def main():
    parser = argparse.ArgumentParser(description="复算有依据的H/C/T/D规则分；不自动解题或预测得分率。")
    parser.add_argument("input", type=Path, help="单小问对象，或含questions数组的JSON文件")
    parser.add_argument("--scope", choices=("auto", "question", "paper"), default="auto",
                        help="分析范围；多小问单题可设question；旧数组默认paper")
    parser.add_argument("--output", type=Path, help="结果JSON；省略则输出到终端")
    parser.add_argument("--suggest-labels", action="store_true",
                        help="[需完整包] 使用TypeSafe Jev模型建议标签；skill bundle不支持，请安装完整包: pip install question-difficulty-analysis[typesafe]")
    parser.add_argument("--confidence-threshold", type=float, default=0.6,
                        help="Jev建议的置信度阈值（默认0.6；需--suggest-labels）")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8-sig"))
        
        # Handle --suggest-labels
        if args.suggest_labels:
            print("错误：--suggest-labels 需要完整包，skill bundle 不包含此功能。", file=sys.stderr)
            print("请安装完整包: pip install question-difficulty-analysis[typesafe]", file=sys.stderr)
            print("然后运行: python -m question_difficulty <input> --suggest-labels", file=sys.stderr)
            return 2
        
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
