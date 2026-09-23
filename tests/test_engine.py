import copy
import json
from pathlib import Path
import unittest
from question_difficulty.engine import ValidationError, rounded, score_question, score_paper


ROOT = Path(__file__).resolve().parents[1]


def question():
    return json.loads((ROOT/"examples/minimal.json").read_text(encoding="utf-8"))["questions"][0]


class Rules(unittest.TestCase):
    def test_round_half_up(self):
        self.assertEqual(rounded(2.5), 3)
        self.assertEqual(rounded(0.5), 1)

    def test_exact_half_load(self):
        q = question()
        q["steps"] = [q["steps"][0]]
        q["steps"][0]["dimensions"] = dict(zip("KRAVPI", [0,0,1,0,0,0]))
        self.assertEqual(score_question(q)["H"], 8)

    def test_parallel_paths_are_not_summed(self):
        q = question()
        root = q["steps"][0]
        root["dimensions"] = {k:2 for k in "KRAVPI"}
        other = copy.deepcopy(root)
        other["id"] = "other"
        q["steps"] = [root, other]
        self.assertEqual(score_question(q)["E"], 1)

    def test_dependency_depth_cap(self):
        q = question()
        template = q["steps"][0]
        q["steps"] = []
        for i in range(5):
            step = copy.deepcopy(template)
            step.update(id=str(i), dependencies=[str(i-1)] if i else [],
                        dimensions={k:2 for k in "KRAVPI"})
            q["steps"].append(step)
        r = score_question(q)
        self.assertEqual([p["d"] for p in r["path"]], [1,1.1,1.2,1.3,1.3])
        self.assertEqual(r["E"], 5.9)

    def test_repetition_needs_evidence(self):
        q = question()
        q["steps"][0]["repeat_group"] = "same"
        with self.assertRaises(ValidationError):
            score_question(q)

    def test_repetition_path_local(self):
        q = question()
        template = q["steps"][0]
        q["steps"] = []
        for i in range(4):
            step = copy.deepcopy(template)
            step.update(id=str(i), dependencies=[str(i-1)] if i else [],
                        dimensions={k:2 for k in "KRAVPI"}, repeat_group="mechanical",
                        repeat_evidence="测试用重复同一代入动作；非推理步骤")
            q["steps"].append(step)
        self.assertEqual([p["r"] for p in score_question(q)["path"]], [1,.7,.4,.4])

    def test_pending_is_not_zero(self):
        pending = {"id":"p", "pending":True, "issue":"题干版本冲突", "score":5}
        r = score_paper([pending])
        self.assertIsNone(r["statistics"]["mean"])
        self.assertEqual(r["statistics"]["valid"], 0)
        self.assertIsNone(r["questions"][0]["D"])

    def test_missing_marks_not_fabricated(self):
        q = question()
        q["score"] = None
        r = score_paper([q])
        self.assertIsNone(r["statistics"]["whole_paper_weighted_mean"])
        self.assertEqual(r["statistics"]["known_points"], 0)

    def test_weighted_full_and_subset(self):
        q = question()
        q["score"] = 4
        result = score_paper([q])
        self.assertEqual(result["statistics"]["whole_paper_weighted_mean"], result["questions"][0]["D"])
        result = score_paper([q,{"id":"pending","pending":True,"issue":"缺图","score":6}])
        self.assertEqual(result["statistics"]["known_points_coverage"], .4)
        self.assertIsNone(result["statistics"]["whole_paper_weighted_mean"])

    def test_cycles_rejected(self):
        q = question()
        q["steps"][0]["dependencies"] = [q["steps"][0]["id"]]
        with self.assertRaises(ValidationError): score_question(q)

    def test_unknown_dependency_rejected(self):
        q = question()
        q["steps"][0]["dependencies"] = ["missing"]
        with self.assertRaises(ValidationError): score_question(q)

    def test_unknown_risk_rejected(self):
        q = question()
        q["t"][0] = None
        with self.assertRaises(ValidationError): score_question(q)

    def test_dimensions_require_evidence(self):
        q = question()
        q["steps"][0]["dimension_evidence"]["R"] = ""
        with self.assertRaises(ValidationError): score_question(q)

    def test_bool_is_not_dimension(self):
        q = question()
        q["steps"][0]["dimensions"]["K"] = True
        with self.assertRaises(ValidationError): score_question(q)

    def test_b_does_not_change_d(self):
        q = question()
        before = score_question(q)
        q["B"] = 3
        after = score_question(q)
        self.assertEqual(before["D"],after["D"])

    def test_stale_scores_ignored(self):
        q = question()
        before = score_question(q)
        q.update(H=100, C=100, T=100, D=100)
        q["steps"][0]["s"] = 1
        self.assertEqual(before, score_question(q))

    def test_duplicate_question_rejected(self):
        q = question()
        with self.assertRaises(ValidationError): score_paper([q,q])

    def test_path_limit(self):
        q = question()
        other = copy.deepcopy(q["steps"][0])
        other["id"] = "other"
        q["steps"] = [q["steps"][0],other]
        with self.assertRaises(ValidationError): score_question(q,max_paths=1)

    def test_four_year_regression(self):
        data = json.loads((ROOT/"data/shanghai-2023-2026.json").read_text(encoding="utf-8"))
        counts = {2023:28,2024:29,2025:29,2026:29}
        scored = 0
        for year, n in counts.items():
            questions = [q for q in data["questions"] if q["year"]==year]
            self.assertEqual(len(questions), n)
            actual = score_paper(questions)
            for old,new in zip(questions, actual["questions"]):
                for key in ("H","C","T","D","B"):
                    self.assertEqual(old[key],new[key],(year,old["id"],key))
                scored += new["D"] is not None
        self.assertEqual(scored,106)


if __name__ == "__main__": unittest.main()
