import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "question-difficulty-analysis"


class SkillBundle(unittest.TestCase):
    def test_bundled_rules_and_engine_match_project(self):
        self.assertEqual(
            (SKILL / "references" / "完整工作规则.md").read_bytes(),
            (ROOT / "prompts" / "整卷难度量化与解析关键批注-通用提示词.md").read_bytes(),
        )
        for name in ("__init__.py", "__main__.py", "engine.py"):
            self.assertEqual(
                (SKILL / "scripts" / "question_difficulty" / name).read_bytes(),
                (ROOT / "question_difficulty" / name).read_bytes(),
            )

    def test_bundled_cli_runs_without_project_import(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "result.json"
            for name, scope, scores in (
                ("single-question.json", "question", [21]),
                ("single-multipart.json", "question", [14, 40, 77]),
            ):
                run = subprocess.run(
                    [sys.executable, str(SKILL / "scripts" / "score.py"),
                     str(SKILL / "examples" / name), "--output", str(destination)],
                    cwd=directory, capture_output=True, text=True,
                )
                self.assertEqual(run.returncode, 0, run.stderr)
                result = json.loads(destination.read_text(encoding="utf-8"))
                self.assertEqual(result["scope"], scope)
                actual = ([result["question"]["D"]] if "question" in result
                          else [q["D"] for q in result["questions"]])
                self.assertEqual(actual, scores)


if __name__ == "__main__":
    unittest.main()
