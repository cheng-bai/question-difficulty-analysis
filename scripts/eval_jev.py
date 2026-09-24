#!/usr/bin/env python3
"""Evaluate Jev label suggestions against human-labeled Shanghai data.

This script compares Jev's suggestions against the 106 non-pending labeled
questions in data/shanghai-2023-2026.json. It computes:
- Per-dimension exact agreement and within-one-level agreement
- Cohen's kappa for each dimension
- Same metrics for T items and B breakthrough level
- Downstream D/tier agreement and MAE
- Confidence-vs-accuracy table for threshold tuning

Usage:
    python scripts/eval_jev.py [--limit N] [--sample N] [--output FILE]

Requires:
    - TYPESAFE_API_KEY environment variable
    - pip install question-difficulty-analysis[typesafe]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@dataclass
class DimensionMetrics:
    """Metrics for a single dimension."""
    
    name: str
    total: int = 0
    exact_match: int = 0
    within_one: int = 0
    predictions: list[int] = field(default_factory=list)
    actuals: list[int] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)
    
    @property
    def exact_agreement(self) -> float:
        return self.exact_match / self.total if self.total > 0 else 0.0
    
    @property
    def within_one_agreement(self) -> float:
        return self.within_one / self.total if self.total > 0 else 0.0
    
    def cohens_kappa(self) -> float:
        """Compute Cohen's kappa for ordinal data."""
        if self.total == 0:
            return 0.0
        
        # Build confusion matrix
        n_classes = 3  # 0, 1, 2
        confusion = [[0] * n_classes for _ in range(n_classes)]
        for pred, actual in zip(self.predictions, self.actuals):
            pred = min(pred, n_classes - 1)
            actual = min(actual, n_classes - 1)
            confusion[actual][pred] += 1
        
        # Calculate observed agreement
        po = sum(confusion[i][i] for i in range(n_classes)) / self.total
        
        # Calculate expected agreement
        row_sums = [sum(confusion[i]) for i in range(n_classes)]
        col_sums = [sum(confusion[i][j] for i in range(n_classes)) for j in range(n_classes)]
        pe = sum(row_sums[i] * col_sums[i] for i in range(n_classes)) / (self.total ** 2)
        
        if pe == 1.0:
            return 1.0 if po == 1.0 else 0.0
        
        return (po - pe) / (1 - pe)


@dataclass
class EvaluationResults:
    """Complete evaluation results."""
    
    dimension_metrics: dict[str, DimensionMetrics] = field(default_factory=dict)
    t_item_metrics: dict[int, DimensionMetrics] = field(default_factory=dict)
    b_metrics: DimensionMetrics = field(default_factory=lambda: DimensionMetrics("B"))
    
    d_predictions: list[int] = field(default_factory=list)
    d_actuals: list[int] = field(default_factory=list)
    tier_predictions: list[str] = field(default_factory=list)
    tier_actuals: list[str] = field(default_factory=list)
    
    confidence_buckets: dict[str, dict[str, list[tuple[float, bool]]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(list))
    )
    
    questions_evaluated: int = 0
    steps_evaluated: int = 0
    errors: list[str] = field(default_factory=list)
    
    @property
    def d_mae(self) -> float:
        """Mean absolute error for D scores."""
        if not self.d_predictions:
            return 0.0
        return sum(abs(p - a) for p, a in zip(self.d_predictions, self.d_actuals)) / len(self.d_predictions)
    
    @property
    def d_exact_agreement(self) -> float:
        """Exact agreement for D scores."""
        if not self.d_predictions:
            return 0.0
        return sum(p == a for p, a in zip(self.d_predictions, self.d_actuals)) / len(self.d_predictions)
    
    @property
    def tier_agreement(self) -> float:
        """Agreement for tier classification."""
        if not self.tier_predictions:
            return 0.0
        return sum(p == a for p, a in zip(self.tier_predictions, self.tier_actuals)) / len(self.tier_predictions)


def get_tier(d: int) -> str:
    """Get tier from D score."""
    if d < 35:
        return "基础"
    elif d < 65:
        return "中档"
    else:
        return "难题"


def compute_d_from_suggestions(step_suggestions, t_values, weights=None) -> int:
    """Compute D score from Jev suggestions using HCT rules."""
    from decimal import Decimal, ROUND_HALF_UP
    
    if weights is None:
        weights = tuple(map(Decimal, (".20", ".25", ".15", ".15", ".15", ".10")))
    
    dims = "KRAVPI"
    
    # Calculate step loads
    loads = []
    for step_s in step_suggestions:
        load = sum(
            weights[i] * step_s.dimensions[dim].value / 2
            for i, dim in enumerate(dims)
        )
        loads.append(load)
    
    if not loads:
        return 0
    
    # H = max step load * 100
    H = int(Decimal(str(float(max(loads)) * 100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    
    # C = simplified (just use max load as estimate since we don't have full path info)
    best = max(loads)
    C = int(Decimal(str(100 * (1 - (-best / 3).__float__().__neg__()))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    
    # T = 10 * sum(t)
    T = 10 * sum(t_values)
    
    # D = 0.45H + 0.35C + 0.20T
    D = int(Decimal(str(0.45 * H + 0.35 * C + 0.20 * T)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    
    return D


def evaluate_question(
    question: dict,
    results: EvaluationResults,
    config: Any,
) -> bool:
    """Evaluate a single question. Returns True if successful."""
    from question_difficulty.jev_suggest import suggest_question_labels
    
    try:
        suggestion = suggest_question_labels(question, config)
        if suggestion is None:
            results.errors.append(f"Question {question.get('id')}: suggestion returned None")
            return False
        
        results.questions_evaluated += 1
        
        # Evaluate step dimensions
        steps_by_id = {s["id"]: s for s in question.get("steps", [])}
        
        for step_s in suggestion.step_suggestions:
            step = steps_by_id.get(step_s.step_id)
            if step is None:
                continue
            
            results.steps_evaluated += 1
            
            for dim in "KRAVPI":
                if dim not in results.dimension_metrics:
                    results.dimension_metrics[dim] = DimensionMetrics(dim)
                
                metrics = results.dimension_metrics[dim]
                
                actual = step["dimensions"].get(dim)
                if actual is None:
                    continue
                
                predicted = step_s.dimensions[dim].value
                confidence = step_s.dimensions[dim].confidence
                
                metrics.total += 1
                metrics.predictions.append(predicted)
                metrics.actuals.append(actual)
                metrics.confidences.append(confidence)
                
                if predicted == actual:
                    metrics.exact_match += 1
                if abs(predicted - actual) <= 1:
                    metrics.within_one += 1
                
                # Record for confidence analysis
                bucket = f"{int(confidence * 10) / 10:.1f}"
                results.confidence_buckets[dim][bucket].append((confidence, predicted == actual))
        
        # Evaluate T items
        actual_t = question.get("t", [])
        if len(actual_t) == 5:
            for i, (pred_item, actual_val) in enumerate(
                zip(suggestion.t_suggestion.items, actual_t), 1
            ):
                if i not in results.t_item_metrics:
                    results.t_item_metrics[i] = DimensionMetrics(f"t{i}")
                
                metrics = results.t_item_metrics[i]
                predicted = pred_item["value"]
                confidence = pred_item["confidence"]
                
                metrics.total += 1
                metrics.predictions.append(predicted)
                metrics.actuals.append(actual_val)
                metrics.confidences.append(confidence)
                
                if predicted == actual_val:
                    metrics.exact_match += 1
                if abs(predicted - actual_val) <= 1:
                    metrics.within_one += 1
                
                bucket = f"{int(confidence * 10) / 10:.1f}"
                results.confidence_buckets[f"t{i}"][bucket].append((confidence, predicted == actual_val))
        
        # Evaluate B
        actual_b = question.get("B")
        if actual_b is not None:
            metrics = results.b_metrics
            predicted = suggestion.b_suggestion.value
            confidence = suggestion.b_suggestion.confidence
            
            metrics.total += 1
            metrics.predictions.append(predicted)
            metrics.actuals.append(actual_b)
            metrics.confidences.append(confidence)
            
            if predicted == actual_b:
                metrics.exact_match += 1
            if abs(predicted - actual_b) <= 1:
                metrics.within_one += 1
            
            bucket = f"{int(confidence * 10) / 10:.1f}"
            results.confidence_buckets["B"][bucket].append((confidence, predicted == actual_b))
        
        # Evaluate downstream D and tier
        actual_d = question.get("D")
        if actual_d is not None and len(suggestion.t_suggestion.values) == 5:
            predicted_d = compute_d_from_suggestions(
                suggestion.step_suggestions,
                suggestion.t_suggestion.values,
            )
            
            results.d_predictions.append(predicted_d)
            results.d_actuals.append(actual_d)
            
            predicted_tier = get_tier(predicted_d)
            actual_tier = question.get("band", get_tier(actual_d))
            
            results.tier_predictions.append(predicted_tier)
            results.tier_actuals.append(actual_tier)
        
        return True
        
    except Exception as e:
        results.errors.append(f"Question {question.get('id')}: {str(e)}")
        return False


def format_results(results: EvaluationResults) -> str:
    """Format evaluation results as a report."""
    lines = []
    lines.append("=" * 60)
    lines.append("Jev 标签建议评估报告")
    lines.append("=" * 60)
    lines.append("")
    
    lines.append(f"评估问题数: {results.questions_evaluated}")
    lines.append(f"评估步骤数: {results.steps_evaluated}")
    if results.errors:
        lines.append(f"错误数: {len(results.errors)}")
    lines.append("")
    
    # Dimension metrics
    lines.append("-" * 40)
    lines.append("六维 (K/R/A/V/P/I) 评估结果")
    lines.append("-" * 40)
    lines.append(f"{'维度':<6} {'样本数':<8} {'精确一致':<12} {'差1以内':<12} {'Cohen κ':<10}")
    lines.append("-" * 40)
    
    for dim in "KRAVPI":
        if dim in results.dimension_metrics:
            m = results.dimension_metrics[dim]
            lines.append(
                f"{dim:<6} {m.total:<8} {m.exact_agreement:.2%}{'':>5} "
                f"{m.within_one_agreement:.2%}{'':>5} {m.cohens_kappa():.3f}"
            )
    lines.append("")
    
    # T item metrics
    lines.append("-" * 40)
    lines.append("T 风险项评估结果")
    lines.append("-" * 40)
    lines.append(f"{'项目':<6} {'样本数':<8} {'精确一致':<12} {'差1以内':<12} {'Cohen κ':<10}")
    lines.append("-" * 40)
    
    for i in range(1, 6):
        if i in results.t_item_metrics:
            m = results.t_item_metrics[i]
            lines.append(
                f"t{i:<5} {m.total:<8} {m.exact_agreement:.2%}{'':>5} "
                f"{m.within_one_agreement:.2%}{'':>5} {m.cohens_kappa():.3f}"
            )
    lines.append("")
    
    # B metrics
    lines.append("-" * 40)
    lines.append("B 突破难度评估结果")
    lines.append("-" * 40)
    m = results.b_metrics
    if m.total > 0:
        lines.append(f"样本数: {m.total}")
        lines.append(f"精确一致: {m.exact_agreement:.2%}")
        lines.append(f"差1以内: {m.within_one_agreement:.2%}")
        lines.append(f"Cohen κ: {m.cohens_kappa():.3f}")
    lines.append("")
    
    # D and tier metrics
    lines.append("-" * 40)
    lines.append("D 规则分与档位评估结果")
    lines.append("-" * 40)
    if results.d_predictions:
        lines.append(f"样本数: {len(results.d_predictions)}")
        lines.append(f"D 平均绝对误差 (MAE): {results.d_mae:.2f}")
        lines.append(f"D 精确一致: {results.d_exact_agreement:.2%}")
        lines.append(f"档位一致率: {results.tier_agreement:.2%}")
    lines.append("")
    
    # Confidence vs accuracy table
    lines.append("-" * 40)
    lines.append("置信度 vs 准确率表 (用于阈值调优)")
    lines.append("-" * 40)
    
    all_buckets = set()
    for dim_buckets in results.confidence_buckets.values():
        all_buckets.update(dim_buckets.keys())
    
    if all_buckets:
        sorted_buckets = sorted(all_buckets, reverse=True)
        
        lines.append(f"{'置信度':<10} {'样本数':<10} {'准确率':<10}")
        lines.append("-" * 30)
        
        cumulative = []
        for bucket in sorted_buckets:
            count = 0
            correct = 0
            for dim_buckets in results.confidence_buckets.values():
                for conf, is_correct in dim_buckets.get(bucket, []):
                    count += 1
                    if is_correct:
                        correct += 1
            if count > 0:
                cumulative.append((bucket, count, correct))
        
        for bucket, count, correct in cumulative:
            acc = correct / count if count > 0 else 0
            lines.append(f"≥{bucket:<9} {count:<10} {acc:.2%}")
    
    lines.append("")
    
    # Warnings
    lines.append("-" * 40)
    lines.append("注意事项")
    lines.append("-" * 40)
    lines.append("1. Jev 只建议标签，D 仍由规则计算")
    lines.append("2. TypeSafe 文档指出非英文文本准确率较低")
    lines.append("3. 阈值需在上海案例上调优后使用")
    lines.append("4. 本评估未声明结果代表最终性能")
    
    if results.errors:
        lines.append("")
        lines.append("-" * 40)
        lines.append("错误列表")
        lines.append("-" * 40)
        for error in results.errors[:10]:
            lines.append(f"  - {error}")
        if len(results.errors) > 10:
            lines.append(f"  ... 和 {len(results.errors) - 10} 个其他错误")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="评估 Jev 标签建议与上海数据的一致性"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="限制评估的问题数量"
    )
    parser.add_argument(
        "--sample", type=int, default=None,
        help="随机抽样评估的问题数量"
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="输出结果JSON文件"
    )
    parser.add_argument(
        "--confidence-threshold", type=float, default=0.6,
        help="置信度阈值"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="随机种子"
    )
    args = parser.parse_args()
    
    # Check API key
    if not os.environ.get("TYPESAFE_API_KEY"):
        print("错误: TYPESAFE_API_KEY 环境变量未设置", file=sys.stderr)
        print("此脚本仅在设置了 API key 时运行", file=sys.stderr)
        return 1
    
    # Check SDK
    try:
        from question_difficulty.jev_suggest import is_available, SuggestionConfig
    except ImportError:
        print("错误: typesafe-sdk 未安装", file=sys.stderr)
        print("请运行: pip install question-difficulty-analysis[typesafe]", file=sys.stderr)
        return 1
    
    available, msg = is_available()
    if not available:
        print(f"错误: Jev 不可用 - {msg}", file=sys.stderr)
        return 1
    
    # Load data
    data_path = ROOT / "data" / "shanghai-2023-2026.json"
    if not data_path.exists():
        print(f"错误: 数据文件不存在: {data_path}", file=sys.stderr)
        return 1
    
    data = json.loads(data_path.read_text(encoding="utf-8"))
    
    # Filter non-pending questions
    questions = [
        q for q in data["questions"]
        if not q.get("pending") and q.get("D") is not None
    ]
    
    print(f"数据集中有 {len(questions)} 个非待复核问题", file=sys.stderr)
    
    # Apply limit/sample
    if args.sample:
        random.seed(args.seed)
        questions = random.sample(questions, min(args.sample, len(questions)))
        print(f"随机抽样 {len(questions)} 个问题", file=sys.stderr)
    elif args.limit:
        questions = questions[:args.limit]
        print(f"限制为前 {len(questions)} 个问题", file=sys.stderr)
    
    # Evaluate
    config = SuggestionConfig(confidence_threshold=args.confidence_threshold)
    results = EvaluationResults()
    
    print(f"开始评估 {len(questions)} 个问题...", file=sys.stderr)
    
    for i, q in enumerate(questions):
        print(f"  [{i+1}/{len(questions)}] 评估问题 {q.get('id')}...", file=sys.stderr)
        evaluate_question(q, results, config)
    
    # Output results
    report = format_results(results)
    print(report)
    
    # Save JSON if requested
    if args.output:
        output_data = {
            "questions_evaluated": results.questions_evaluated,
            "steps_evaluated": results.steps_evaluated,
            "errors": results.errors,
            "dimension_metrics": {
                dim: {
                    "total": m.total,
                    "exact_agreement": m.exact_agreement,
                    "within_one_agreement": m.within_one_agreement,
                    "cohens_kappa": m.cohens_kappa(),
                }
                for dim, m in results.dimension_metrics.items()
            },
            "t_item_metrics": {
                str(i): {
                    "total": m.total,
                    "exact_agreement": m.exact_agreement,
                    "within_one_agreement": m.within_one_agreement,
                    "cohens_kappa": m.cohens_kappa(),
                }
                for i, m in results.t_item_metrics.items()
            },
            "b_metrics": {
                "total": results.b_metrics.total,
                "exact_agreement": results.b_metrics.exact_agreement,
                "within_one_agreement": results.b_metrics.within_one_agreement,
                "cohens_kappa": results.b_metrics.cohens_kappa(),
            },
            "d_metrics": {
                "total": len(results.d_predictions),
                "mae": results.d_mae,
                "exact_agreement": results.d_exact_agreement,
            },
            "tier_metrics": {
                "total": len(results.tier_predictions),
                "agreement": results.tier_agreement,
            },
        }
        
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"结果已保存到 {args.output}", file=sys.stderr)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
