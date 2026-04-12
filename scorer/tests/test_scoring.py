#!/usr/bin/env python3
"""
Footnote Scoring Validation — permanent test script.

Validates that:
1. compute_score() produces correct scores from dimension inputs (deterministic, no LLM)
2. All test case YAML files load and their expected dimensions match their expected scores
3. (Optional) LLM scoring against live models matches expected dimensions

Usage:
    # Run offline tests only (no LLM calls, always works)
    python scorer/tests/test_scoring.py

    # Run with live LLM validation
    CLOUD_API_KEY=... python scorer/tests/test_scoring.py --live --models "kimi-k2.5@https://ollama.com/v1"

    # Run with multiple models
    CLOUD_API_KEY=... python scorer/tests/test_scoring.py --live \\
        --models "glm-5.1@https://ollama.com/v1" \\
                 "minimax-m2.7@https://ollama.com/v1" \\
                 "kimi-k2.5@https://ollama.com/v1"
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure we can import from scorer/
SCORER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCORER_DIR))

import yaml
from score import (
    compute_score,
    get_risk_level,
    load_criteria,
    get_max_points,
    build_prompt,
    normalize_broad_scope,
    VALID_TAGS,
)

# Ensure UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')


CASES_DIR = SCORER_DIR / "test_cases"


def load_all_cases() -> list[dict]:
    cases = []
    for f in sorted(CASES_DIR.glob("*.yaml")):
        with open(f) as fh:
            cases.append(yaml.safe_load(fh))
    return cases


def test_criteria_loads():
    """Verify scoring_criteria.yaml loads and has expected structure."""
    import score
    score._criteria_cache = None
    criteria = load_criteria(str(SCORER_DIR / "scoring_criteria.yaml"))

    assert "dimensions" in criteria, "Missing 'dimensions' key"
    assert "risk_thresholds" in criteria, "Missing 'risk_thresholds' key"
    assert len(criteria["dimensions"]) >= 6, f"Expected >= 6 dimensions, got {len(criteria['dimensions'])}"

    max_pts = get_max_points(criteria)
    assert max_pts == 10, f"Expected max_points=10, got {max_pts}"

    return criteria


def test_deterministic_scoring(criteria):
    """Verify compute_score() produces correct results for all test cases."""
    cases = load_all_cases()
    passed = 0
    failed = 0

    for case in cases:
        exp = case["expected"]
        dims = {
            "cia": exp["cia"],
            "change_nature": exp["change_nature"],
            "actionability": exp["actionability"],
            "broad_scope": exp["broad_scope"],
        }
        score = compute_score(dims, criteria)
        risk = get_risk_level(score, criteria)

        if score == exp["score"] and risk == exp["risk_level"]:
            passed += 1
            print(f"  PASS  {case['id']:<42} score={score} risk={risk}")
        else:
            failed += 1
            print(f"  FAIL  {case['id']:<42} score={score} (exp {exp['score']}) risk={risk} (exp {exp['risk_level']})")

    return passed, failed


def test_edge_cases(criteria):
    """Verify scoring edge cases."""
    passed = 0
    failed = 0

    # All zeros
    dims_zero = {"cia": {"confidentiality": False, "integrity": False, "availability": False},
                 "change_nature": "cosmetic", "actionability": "none", "broad_scope": "none"}
    s = compute_score(dims_zero, criteria)
    if s == 0.0:
        passed += 1
        print(f"  PASS  all-zeros → {s}")
    else:
        failed += 1
        print(f"  FAIL  all-zeros → {s} (expected 0.0)")

    # All maxed
    dims_max = {"cia": {"confidentiality": True, "integrity": True, "availability": True},
                "change_nature": "critical", "actionability": "required", "broad_scope": "existing"}
    s = compute_score(dims_max, criteria)
    if s == 10.0:
        passed += 1
        print(f"  PASS  all-maxed → {s}")
    else:
        failed += 1
        print(f"  FAIL  all-maxed → {s} (expected 10.0)")

    # Unknown enum value defaults gracefully
    dims_bad = {"cia": {"confidentiality": False, "integrity": False, "availability": False},
                "change_nature": "nonexistent", "actionability": "none", "broad_scope": "none"}
    s = compute_score(dims_bad, criteria)
    if s == 0.0:
        passed += 1
        print(f"  PASS  bad-enum → {s} (graceful fallback)")
    else:
        failed += 1
        print(f"  FAIL  bad-enum → {s} (expected 0.0)")

    return passed, failed


def test_prompt_builds(criteria):
    """Verify prompt template renders without errors."""
    diff_data = {
        "repo_name": "test-repo",
        "commit_hash": "a" * 40,
        "commit_date": "2024-01-01",
        "commit_message": "Test commit",
        "author": "test@example.com",
        "files_changed": ["test.md"],
        "diff_text": "+new line\n-old line",
        "stats": {},
    }
    prompt = build_prompt(diff_data, criteria)
    assert len(prompt) > 100, f"Prompt too short: {len(prompt)} chars"
    assert "cosmetic" in prompt, "Missing dimension levels in prompt"
    assert "test-repo" in prompt, "Missing repo_name in prompt"
    print(f"  PASS  prompt renders ({len(prompt)} chars)")
    return 1, 0


def parse_model_spec(spec: str) -> dict:
    if "@" in spec:
        model, base_url = spec.split("@", 1)
    else:
        model = spec
        base_url = os.environ.get("CLOUD_OLLAMA_URL", "http://localhost:11434/v1")

    key_env = model.upper().replace("-", "_").replace(":", "_").replace(".", "_") + "_API_KEY"
    api_key = os.environ.get(key_env, os.environ.get("CLOUD_API_KEY", ""))
    return {"model": model, "base_url": base_url, "api_key": api_key}


def compare_dims(actual: dict, expected: dict) -> list[str]:
    divergent = []
    for key in ["confidentiality", "integrity", "availability"]:
        if actual.get("cia", {}).get(key, False) != expected.get("cia", {}).get(key, False):
            divergent.append(key[0].upper())
    if actual.get("change_nature") != expected.get("change_nature"):
        divergent.append("nature")
    if actual.get("actionability") != expected.get("actionability"):
        divergent.append("action")
    if normalize_broad_scope(actual.get("broad_scope", "none")) != normalize_broad_scope(expected.get("broad_scope", "none")):
        divergent.append("scope")
    return divergent


def format_cia(cia: dict) -> str:
    c = "+" if cia.get("confidentiality") else "-"
    i = "+" if cia.get("integrity") else "-"
    a = "+" if cia.get("availability") else "-"
    return f"{c}{i}{a}"


def test_live_models(criteria, model_specs: list[str]):
    """Run test cases against live LLM models."""
    from openai import OpenAI

    cases = load_all_cases()
    models = [parse_model_spec(m) for m in model_specs]

    print(f"\n  Running {len(cases)} cases x {len(models)} models = {len(cases) * len(models)} LLM calls...")
    print(f"  {'Case':<40} | {'Model':<18} | {'CIA':<5} | {'Nature':<15} | {'Action':<10} | {'Scope':<5} | {'Score':<5} | {'Exp':<5} | {'Diff':<5} | Result")
    print(f"  {'-'*130}")

    total = 0
    passed = 0
    results = []

    for case in cases:
        exp = case["expected"]
        exp_dims = {
            "cia": exp["cia"],
            "change_nature": exp["change_nature"],
            "actionability": exp["actionability"],
            "broad_scope": exp["broad_scope"],
        }

        diff_data = {
            "repo_name": "test-repo",
            "commit_hash": "0" * 40,
            "commit_date": "2024-01-01",
            "commit_message": case.get("commit_message", ""),
            "author": "test@example.com",
            "files_changed": ["test-file.md"],
            "diff_text": case.get("diff_snippet", ""),
            "stats": {},
        }
        prompt = build_prompt(diff_data, criteria)

        for model_spec in models:
            total += 1
            client = OpenAI(base_url=model_spec["base_url"], api_key=model_spec["api_key"])

            try:
                response = client.chat.completions.create(
                    model=model_spec["model"],
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=4000,
                    temperature=0.2,
                )
                text = response.choices[0].message.content.strip()
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0]
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0]

                result = json.loads(text)
                dims = {
                    "cia": result.get("cia", {}),
                    "change_nature": result.get("change_nature", "cosmetic"),
                    "actionability": result.get("actionability", "none"),
                    "broad_scope": normalize_broad_scope(result.get("broad_scope", "none")),
                }
                score = compute_score(dims, criteria)
                risk = get_risk_level(score, criteria)
                divergent = compare_dims(dims, exp_dims)
                score_diff = score - exp["score"]

                cia_str = format_cia(dims.get("cia", {}))
                nature = dims.get("change_nature", "?")[:13]
                action = dims.get("actionability", "?")[:8]
                scope = dims.get("broad_scope", "none")[:3]
                diff_str = f"{score_diff:+.1f}" if score_diff != 0 else "0"

                if not divergent:
                    status = "PASS"
                    passed += 1
                else:
                    status = f"FAIL ({','.join(divergent)})"

                results.append({
                    "case": case["id"], "model": model_spec["model"],
                    "score": score, "expected": exp["score"], "diff": score_diff,
                    "dims": dims, "divergent": divergent, "pass": not divergent
                })

                print(f"  {case['id'][:38]:<40} | {model_spec['model'][:16]:<18} | {cia_str:<5} | {nature:<15} | {action:<10} | {scope:<5} | {score:<5} | {exp['score']:<5} | {diff_str:<5} | {status}")

            except Exception as e:
                results.append({
                    "case": case["id"], "model": model_spec["model"],
                    "score": None, "expected": exp["score"], "diff": None,
                    "dims": {}, "divergent": ["ERROR"], "pass": False
                })
                print(f"  {case['id'][:38]:<40} | {model_spec['model'][:16]:<18} | ERR   | {'':15} | {'':10} | {'':5} | {'':5} | {exp['score']:<5} | {'':5} | FAIL: {str(e)[:40]}")

    # Summary
    print(f"\n  {'='*130}")
    print(f"  {len(models)} model(s) x {len(cases)} case(s) = {total} runs. Passed: {passed}/{total} ({100*passed//max(total,1)}%)")

    if results:
        from collections import Counter
        all_div = []
        for r in results:
            all_div.extend(r["divergent"])
        if all_div:
            print(f"  Divergent dimensions: {dict(Counter(all_div))}")

        # Per-model summary
        print(f"\n  Per-model breakdown:")
        for model_spec in models:
            model_results = [r for r in results if r["model"] == model_spec["model"]]
            model_pass = sum(1 for r in model_results if r["pass"])
            model_diffs = [abs(r["diff"]) for r in model_results if r["diff"] is not None]
            avg_diff = sum(model_diffs) / len(model_diffs) if model_diffs else 0
            print(f"    {model_spec['model']:<20} exact={model_pass}/{len(model_results)}  avg_score_diff={avg_diff:.1f}")

    return passed, total - passed


def main():
    parser = argparse.ArgumentParser(description="Footnote Scoring Validation")
    parser.add_argument("--live", action="store_true", help="Run live LLM tests (requires API key)")
    parser.add_argument("--models", nargs="*", help="Model specs for live tests: 'model@url'")
    args = parser.parse_args()

    total_passed = 0
    total_failed = 0

    # Test 1: Criteria loads
    print("\n[1] Criteria loading")
    criteria = test_criteria_loads()
    print(f"  PASS  criteria loaded ({len(criteria['dimensions'])} dimensions, max={get_max_points(criteria)} points)")
    total_passed += 1

    # Test 2: Deterministic scoring
    print("\n[2] Deterministic scoring (test cases)")
    p, f = test_deterministic_scoring(criteria)
    total_passed += p
    total_failed += f

    # Test 3: Edge cases
    print("\n[3] Edge cases")
    p, f = test_edge_cases(criteria)
    total_passed += p
    total_failed += f

    # Test 4: Prompt builds
    print("\n[4] Prompt template")
    p, f = test_prompt_builds(criteria)
    total_passed += p
    total_failed += f

    # Test 5: Live LLM (optional)
    if args.live:
        if not args.models:
            print("\n[5] Live LLM tests SKIPPED (no --models specified)")
        else:
            print(f"\n[5] Live LLM validation")
            p, f = test_live_models(criteria, args.models)
            total_passed += p
            total_failed += f
    else:
        print("\n[5] Live LLM tests SKIPPED (use --live to enable)")

    # Final summary
    print(f"\n{'='*60}")
    print(f"Total: {total_passed} passed, {total_failed} failed")
    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    main()
