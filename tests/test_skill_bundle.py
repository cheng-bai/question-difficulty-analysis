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
        # __init__.py and engine.py must match exactly
        for name in ("__init__.py", "engine.py"):
            self.assertEqual(
                (SKILL / "scripts" / "question_difficulty" / name).read_bytes(),
                (ROOT / "question_difficulty" / name).read_bytes(),
            )
    
    def test_bundled_main_has_suggest_labels_fallback(self):
        """Verify skill bundle's __main__.py handles --suggest-labels gracefully.
        
        The bundle's __main__.py is intentionally different from the project's:
        it shows a clear error directing users to install the full package.
        """
        bundle_main = (SKILL / "scripts" / "question_difficulty" / "__main__.py").read_text()
        # Must have the flag for CLI compatibility
        self.assertIn("--suggest-labels", bundle_main)
        # Must show error directing to full package
        self.assertIn("需要完整包", bundle_main)
        self.assertIn("pip install question-difficulty-analysis[typesafe]", bundle_main)
        # Must have score_input function for scoring functionality
        self.assertIn("def score_input", bundle_main)

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
    
    def test_bundled_suggest_labels_shows_error(self):
        """Test that --suggest-labels in bundle shows helpful error."""
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run(
                [sys.executable, str(SKILL / "scripts" / "score.py"),
                 str(SKILL / "examples" / "single-question.json"), "--suggest-labels"],
                cwd=directory, capture_output=True, text=True,
            )
            self.assertEqual(run.returncode, 2)
            self.assertIn("需要完整包", run.stderr)
            self.assertIn("pip install", run.stderr)


if __name__ == "__main__":
    unittest.main()
