import argparse
import json
import sys
from pathlib import Path
from .engine import score_paper, ValidationError


def main():
    parser = argparse.ArgumentParser(description="复算有依据的H/C/T/D规则分；不自动解题或预测得分率。")
    parser.add_argument("input", type=Path, help="JSON文件，含questions数组")
    parser.add_argument("--output", type=Path, help="结果JSON；省略则输出到终端")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValidationError("input must be an object with questions")
        result = score_paper(data.get("questions"))
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
