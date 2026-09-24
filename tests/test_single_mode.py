import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from question_difficulty.__main__ import score_input
from question_difficulty import score_question, ValidationError
ROOT = Path(__file__).resolve().parents[1]
def read(name):
    return json.loads((ROOT/'examples'/name).read_text(encoding='utf-8'))
class SingleMode(unittest.TestCase):
    def test_single_matches_existing_algorithm(self):
        q=read('single-question.json');r=score_input(q)
        self.assertEqual(r['question'],score_question(q))
        self.assertNotIn('statistics',r)
    def test_multipart_uses_question_scope_and_unknown_marks(self):
        r=score_input(read('single-multipart.json'))
        self.assertEqual([q['D'] for q in r['questions']],[14,40,77])
        self.assertEqual(r['statistics']['total'],3)
        self.assertEqual(r['scope'],'question')
        self.assertNotIn('whole_paper_weighted_mean',r['statistics'])
        self.assertIsNone(r['statistics']['whole_question_weighted_mean'])
    def test_legacy_default_and_explicit_override(self):
        d=read('minimal.json')
        self.assertEqual(score_input(d)['scope'],'paper')
        r=score_input(d,'question')
        self.assertEqual(r['statistics']['whole_question_weighted_mean'],r['questions'][0]['D'])
        self.assertIn('整题',r['statistics']['weighted_scope'])
        self.assertEqual(score_input(read('single-multipart.json'),'paper')['scope'],'paper')
    def test_pending_is_not_zero(self):
        q={'id':'pending','pending':True,'issue':'缺少条件','score':None}
        self.assertIsNone(score_input(q)['question']['D'])
    def test_invalid_or_ambiguous_scope(self):
        q=read('single-question.json')
        for d,scope in [(q,'paper'),(q,'bad'),({'questions':[q],'steps':[]},'auto'),({'questions':[q],'scope':'bad'},'auto')]:
            with self.assertRaises(ValidationError):score_input(d,scope)
    def test_cli_end_to_end_and_preserves_input(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.json';dest=Path(folder)/'result.json'
            source.write_text(json.dumps(read('single-multipart.json')),encoding='utf-8')
            before=source.read_bytes()
            run=subprocess.run([sys.executable,'-m','question_difficulty',str(source),'--output',str(dest)],cwd=ROOT,capture_output=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(json.loads(dest.read_text(encoding='utf-8'))['scope'],'question')
            run=subprocess.run([sys.executable,'-m','question_difficulty',str(source),'--output',str(source)],cwd=ROOT,capture_output=True)
            self.assertEqual(run.returncode,2)
            self.assertEqual(source.read_bytes(),before)
