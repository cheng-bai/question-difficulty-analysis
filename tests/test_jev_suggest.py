"""Tests for Jev label suggestion module with mocked TypeSafe responses."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, create_autospec

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def make_mock_choice_answer(choice: str, confidence: float = 0.8):
    """Create a mock Choice answer."""
    mock = MagicMock()
    mock.choice = choice
    mock.confidence = confidence
    probs = {str(i): 0.1 for i in range(3)}
    probs[choice] = confidence
    mock.probabilities = probs
    return mock


def make_mock_noul_answer(noul: float):
    """Create a mock Noul answer."""
    mock = MagicMock()
    mock.noul = noul
    return mock


def make_mock_response(dimension_values=None, t_values=None, b_value=0, ambiguity=0.1):
    """Create a mock TypeSafe response."""
    if dimension_values is None:
        dimension_values = {"K": 1, "R": 1, "A": 0, "V": 0, "P": 1, "I": 0}
    if t_values is None:
        t_values = [1, 0, 0, 0, 1]
    
    mock = MagicMock()
    
    # Build choices dict
    choices = {}
    for dim, val in dimension_values.items():
        choices[dim] = make_mock_choice_answer(str(val))
    
    for i, val in enumerate(t_values, 1):
        choices[f"t{i}"] = make_mock_choice_answer(str(val))
    
    choices["B"] = make_mock_choice_answer(str(b_value))
    
    mock.choices = choices
    mock.nouls = {"has_ambiguity": make_mock_noul_answer(ambiguity)}
    
    return mock


def setup_mock_typesafe_sdk():
    """Set up a mock typesafe_sdk module in sys.modules."""
    mock_sdk = MagicMock()
    mock_sdk.TypeSafeClient = MagicMock
    mock_sdk.Choice = MagicMock
    mock_sdk.Score = MagicMock
    mock_sdk.Noul = MagicMock
    mock_sdk.NoulCriteria = MagicMock
    sys.modules['typesafe_sdk'] = mock_sdk
    return mock_sdk


class TestJevSuggestAvailability(unittest.TestCase):
    """Test availability checking."""
    
    def test_api_key_not_set(self):
        """Test behavior when API key is not set."""
        with patch.dict(os.environ, {}, clear=True):
            if "TYPESAFE_API_KEY" in os.environ:
                del os.environ["TYPESAFE_API_KEY"]
            from question_difficulty.jev_suggest import _check_api_key
            self.assertFalse(_check_api_key())
    
    def test_api_key_set(self):
        """Test detection when API key is set."""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            from question_difficulty.jev_suggest import _check_api_key
            self.assertTrue(_check_api_key())


class TestDimensionMapping(unittest.TestCase):
    """Test dimension criteria are correctly defined."""
    
    def test_all_dimensions_defined(self):
        """Test all six dimensions have criteria."""
        from question_difficulty.jev_suggest import DIMENSION_CRITERIA, DIMENSIONS
        
        for dim in DIMENSIONS:
            self.assertIn(dim, DIMENSION_CRITERIA)
            self.assertIn("name", DIMENSION_CRITERIA[dim])
            self.assertIn("levels", DIMENSION_CRITERIA[dim])
            for level in [0, 1, 2]:
                self.assertIn(level, DIMENSION_CRITERIA[dim]["levels"])
    
    def test_t_criteria_defined(self):
        """Test all five T items have criteria."""
        from question_difficulty.jev_suggest import T_CRITERIA
        
        for i in range(1, 6):
            self.assertIn(i, T_CRITERIA)
            self.assertIn("name", T_CRITERIA[i])
            self.assertIn("levels", T_CRITERIA[i])
    
    def test_b_criteria_defined(self):
        """Test all four B levels have criteria."""
        from question_difficulty.jev_suggest import B_CRITERIA
        
        for level in [0, 1, 2, 3]:
            self.assertIn(level, B_CRITERIA)


class TestSuggestionWithMock(unittest.TestCase):
    """Test suggestion logic with mocked TypeSafe client."""
    
    @classmethod
    def setUpClass(cls):
        """Set up mock SDK module."""
        cls.mock_sdk = setup_mock_typesafe_sdk()
    
    def setUp(self):
        self.sample_question = json.loads(
            (ROOT / "examples" / "single-question.json").read_text(encoding="utf-8")
        )
    
    def test_basic_suggestion(self):
        """Test basic suggestion flow."""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(return_value=make_mock_response())
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import suggest_question_labels, SuggestionConfig
                
                config = SuggestionConfig()
                suggestion = suggest_question_labels(self.sample_question, config)
                
                self.assertIsNotNone(suggestion)
                self.assertEqual(len(suggestion.step_suggestions), 1)
                self.assertEqual(len(suggestion.t_suggestion.values), 5)
                self.assertIsNotNone(suggestion.b_suggestion)
    
    def test_no_stem_marks_review(self):
        """Test that questions without question_text/stem are marked for review."""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(return_value=make_mock_response())
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import suggest_question_labels, SuggestionConfig
                
                # Sample question has no question_text or stem field
                suggestion = suggest_question_labels(self.sample_question, SuggestionConfig())
                
                # All step suggestions should be marked for review
                self.assertTrue(suggestion.step_suggestions[0].needs_review)
                self.assertTrue(any("no question_text" in r for r in suggestion.step_suggestions[0].review_reasons))
                
                # T and B should also be marked for review
                self.assertTrue(suggestion.t_suggestion.needs_review)
                self.assertTrue(suggestion.b_suggestion.needs_review)
                
                # Metadata should indicate no question text
                self.assertFalse(suggestion.jev_meta.get("has_question_text", True))
    
    def test_with_stem_no_review_for_missing_stem(self):
        """Test that questions WITH question_text are NOT marked for review due to missing stem."""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(return_value=make_mock_response())
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import suggest_question_labels, SuggestionConfig
                
                # Add question_text to the sample
                question_with_stem = self.sample_question.copy()
                question_with_stem["question_text"] = "设不等式 |x-2|<1 的解集为..."
                
                suggestion = suggest_question_labels(question_with_stem, SuggestionConfig())
                
                # Should not have "no question_text" in review reasons
                self.assertFalse(any("no question_text" in r for r in suggestion.step_suggestions[0].review_reasons))
                
                # Metadata should indicate question text is present
                self.assertTrue(suggestion.jev_meta.get("has_question_text", False))
    
    def test_dimension_values_extracted(self):
        """Test that dimension values are correctly extracted."""
        expected_dims = {"K": 2, "R": 1, "A": 0, "V": 1, "P": 2, "I": 0}
        
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(
                return_value=make_mock_response(dimension_values=expected_dims)
            )
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import suggest_question_labels, SuggestionConfig
                
                suggestion = suggest_question_labels(self.sample_question, SuggestionConfig())
                
                for dim, expected_val in expected_dims.items():
                    actual_val = suggestion.step_suggestions[0].dimensions[dim].value
                    self.assertEqual(actual_val, expected_val, f"Dimension {dim} mismatch")
    
    def test_t_values_extracted(self):
        """Test that T values are correctly extracted."""
        expected_t = [2, 1, 0, 1, 2]
        
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(
                return_value=make_mock_response(t_values=expected_t)
            )
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import suggest_question_labels, SuggestionConfig
                
                suggestion = suggest_question_labels(self.sample_question, SuggestionConfig())
                
                self.assertEqual(suggestion.t_suggestion.values, expected_t)
    
    def test_b_value_extracted(self):
        """Test that B value is correctly extracted."""
        expected_b = 2
        
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(
                return_value=make_mock_response(b_value=expected_b)
            )
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import suggest_question_labels, SuggestionConfig
                
                suggestion = suggest_question_labels(self.sample_question, SuggestionConfig())
                
                self.assertEqual(suggestion.b_suggestion.value, expected_b)


class TestConfidenceGating(unittest.TestCase):
    """Test confidence-based gating behavior."""
    
    @classmethod
    def setUpClass(cls):
        """Set up mock SDK module."""
        if 'typesafe_sdk' not in sys.modules:
            setup_mock_typesafe_sdk()
    
    def setUp(self):
        self.sample_question = json.loads(
            (ROOT / "examples" / "single-question.json").read_text(encoding="utf-8")
        )
    
    def test_low_confidence_marks_review(self):
        """Test that low confidence answers are marked for review."""
        mock_response = MagicMock()
        
        # Create low-confidence K answer
        choices = {}
        for dim in "KRAVPI":
            if dim == "K":
                choices[dim] = make_mock_choice_answer("1", confidence=0.3)
            else:
                choices[dim] = make_mock_choice_answer("0", confidence=0.8)
        
        for i in range(1, 6):
            choices[f"t{i}"] = make_mock_choice_answer("0", confidence=0.8)
        choices["B"] = make_mock_choice_answer("0", confidence=0.8)
        
        mock_response.choices = choices
        mock_response.nouls = {"has_ambiguity": make_mock_noul_answer(0.1)}
        
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(return_value=mock_response)
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import suggest_question_labels, SuggestionConfig
                
                # Add question_text to avoid the no-stem review reason
                question_with_stem = self.sample_question.copy()
                question_with_stem["question_text"] = "设不等式 |x-2|<1 的解集为..."
                
                config = SuggestionConfig(low_confidence_threshold=0.4)
                suggestion = suggest_question_labels(question_with_stem, config)
                
                self.assertTrue(suggestion.step_suggestions[0].needs_review)
                # Now the first/only reason should be about low K confidence
                self.assertTrue(any("K confidence" in r for r in suggestion.step_suggestions[0].review_reasons))
    
    def test_high_confidence_no_review(self):
        """Test that high confidence answers are not marked for review."""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(return_value=make_mock_response())
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import suggest_question_labels, SuggestionConfig
                
                # Add question_text to avoid the no-stem review reason
                question_with_stem = self.sample_question.copy()
                question_with_stem["question_text"] = "设不等式 |x-2|<1 的解集为..."
                
                config = SuggestionConfig(low_confidence_threshold=0.4)
                suggestion = suggest_question_labels(question_with_stem, config)
                
                # With high confidence and question_text present, should not need review
                self.assertFalse(suggestion.step_suggestions[0].needs_review)


class TestAmbiguityDetection(unittest.TestCase):
    """Test material ambiguity detection."""
    
    @classmethod
    def setUpClass(cls):
        """Set up mock SDK module."""
        if 'typesafe_sdk' not in sys.modules:
            setup_mock_typesafe_sdk()
    
    def setUp(self):
        self.sample_question = json.loads(
            (ROOT / "examples" / "single-question.json").read_text(encoding="utf-8")
        )
    
    def test_ambiguity_detected(self):
        """Test that high ambiguity probability triggers detection."""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(
                return_value=make_mock_response(ambiguity=0.75)
            )
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import suggest_question_labels, SuggestionConfig
                
                suggestion = suggest_question_labels(self.sample_question, SuggestionConfig())
                
                self.assertTrue(suggestion.has_ambiguity)
                self.assertIn("歧义", suggestion.ambiguity_note)
    
    def test_no_ambiguity(self):
        """Test that low ambiguity probability is handled correctly."""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(
                return_value=make_mock_response(ambiguity=0.1)
            )
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import suggest_question_labels, SuggestionConfig
                
                suggestion = suggest_question_labels(self.sample_question, SuggestionConfig())
                
                self.assertFalse(suggestion.has_ambiguity)


class TestApplySuggestions(unittest.TestCase):
    """Test applying suggestions to question dict."""
    
    @classmethod
    def setUpClass(cls):
        """Set up mock SDK module."""
        if 'typesafe_sdk' not in sys.modules:
            setup_mock_typesafe_sdk()
    
    def setUp(self):
        self.sample_question = json.loads(
            (ROOT / "examples" / "single-question.json").read_text(encoding="utf-8")
        )
    
    def test_apply_preserves_existing(self):
        """Test that existing labels are preserved by default."""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(
                return_value=make_mock_response(
                    dimension_values={"K": 2, "R": 2, "A": 2, "V": 2, "P": 2, "I": 2}
                )
            )
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import (
                    suggest_question_labels, apply_suggestions_to_question, SuggestionConfig
                )
                
                # Original has K=1
                original_k = self.sample_question["steps"][0]["dimensions"]["K"]
                
                suggestion = suggest_question_labels(self.sample_question, SuggestionConfig())
                result = apply_suggestions_to_question(
                    self.sample_question, suggestion, overwrite_existing=False
                )
                
                # K should be preserved
                self.assertEqual(result["steps"][0]["dimensions"]["K"], original_k)
    
    def test_apply_with_overwrite(self):
        """Test that overwrite_existing=True replaces labels."""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(
                return_value=make_mock_response(
                    dimension_values={"K": 2, "R": 2, "A": 2, "V": 2, "P": 2, "I": 2}
                )
            )
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import (
                    suggest_question_labels, apply_suggestions_to_question, SuggestionConfig
                )
                
                suggestion = suggest_question_labels(self.sample_question, SuggestionConfig())
                result = apply_suggestions_to_question(
                    self.sample_question, suggestion, overwrite_existing=True
                )
                
                # K should be replaced with suggested value
                self.assertEqual(result["steps"][0]["dimensions"]["K"], 2)
    
    def test_apply_adds_metadata(self):
        """Test that jev_meta is added to result."""
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(return_value=make_mock_response())
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import (
                    suggest_question_labels, apply_suggestions_to_question, SuggestionConfig
                )
                
                suggestion = suggest_question_labels(self.sample_question, SuggestionConfig())
                result = apply_suggestions_to_question(self.sample_question, suggestion)
                
                self.assertIn("jev_meta", result)
                self.assertIn("model", result["jev_meta"])


class TestKeyAbsentFallback(unittest.TestCase):
    """Test behavior when API key or SDK is absent."""
    
    def test_no_api_key_returns_none(self):
        """Test that suggest_question_labels returns None without API key."""
        with patch.dict(os.environ, {}, clear=True):
            if "TYPESAFE_API_KEY" in os.environ:
                del os.environ["TYPESAFE_API_KEY"]
            
            from question_difficulty.jev_suggest import suggest_question_labels
            
            sample = {"id": "test", "steps": []}
            result = suggest_question_labels(sample)
            
            self.assertIsNone(result)


class TestExistingTestsStillPass(unittest.TestCase):
    """Ensure existing engine tests still pass."""
    
    def test_engine_import(self):
        """Test that engine module still imports correctly."""
        from question_difficulty.engine import score_question, score_paper
        self.assertTrue(callable(score_question))
        self.assertTrue(callable(score_paper))
    
    def test_minimal_question_still_scores(self):
        """Test that minimal question still scores correctly."""
        from question_difficulty.engine import score_question
        
        question = json.loads(
            (ROOT / "examples" / "minimal.json").read_text(encoding="utf-8")
        )["questions"][0]
        
        result = score_question(question)
        self.assertIsNotNone(result["D"])


class TestFormatSummary(unittest.TestCase):
    """Test formatting of suggestion summary."""
    
    @classmethod
    def setUpClass(cls):
        """Set up mock SDK module."""
        if 'typesafe_sdk' not in sys.modules:
            setup_mock_typesafe_sdk()
    
    def test_format_includes_all_sections(self):
        """Test that format includes all required sections."""
        sample = json.loads(
            (ROOT / "examples" / "single-question.json").read_text(encoding="utf-8")
        )
        
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}):
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.system_one = MagicMock(return_value=make_mock_response())
            
            with patch("typesafe_sdk.TypeSafeClient", return_value=mock_client):
                from question_difficulty.jev_suggest import (
                    suggest_question_labels, format_suggestion_summary, SuggestionConfig
                )
                
                suggestion = suggest_question_labels(sample, SuggestionConfig())
                summary = format_suggestion_summary(suggestion)
                
                self.assertIn("步骤维度建议", summary)
                self.assertIn("T 风险项建议", summary)
                self.assertIn("B 突破难度建议", summary)
                self.assertIn("待教师确认", summary)
                self.assertIn("TypeSafe", summary)


if __name__ == "__main__":
    unittest.main()
