"""
Footnote Test Runner — Cross-model consistency validation.

Feeds test cases through the scoring prompt against one or more LLMs,
compares dimension classifications to expected values, and reports
agreement.

Usage:
    # Run all test cases against default model
    python test_runner.py --cases scorer/test_cases/

    # Run against multiple models
    python test_runner.py --cases scorer/test_cases/ \
        --models "kimi-k2.5:cloud@https://api.moonshot.cn/v1" \
                 "gpt-4o@https://api.openai.com/v1"

    # Single case, verbose
    python test_runner.py --cases scorer/test_cases/api-connections-dynamic-invoke.yaml --verbose
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import yaml
from openai import OpenAI

# Add parent dir so we can import score module
sys.path.insert(0, str(Path(__file__).parent))
from score import (
    load_criteria,
    build_prompt,
    compute_score,
    get_risk_level,
    VALID_TAGS,
)


def load_test_cases(path: str) -> list[dict]:
    """Load test cases from a file or directory."""
    p = Path(path)
    if p.is_file():
        with open(p) as f:
            return [yaml.safe_load(f)]
    elif p.is_dir():
        cases = []
        for f in sorted(p.glob("*.yaml")):
            with open(f) as fh:
                cases.append(yaml.safe_load(fh))
        return cases
    else:
        print(f"Error: {path} is not a file or directory")
        sys.exit(1)


def parse_model_spec(spec: str) -> dict:
    """Parse model spec format: 'model_name@base_url' or just 'model_name'."""
    if "@" in spec:
        model, base_url = spec.split("@", 1)
    else:
        model = spec
        base_url = os.environ.get("CLOUD_OLLAMA_URL", "http://localhost:11434/v1")

    # API key: check MODEL_NAME_API_KEY env var, then CLOUD_API_KEY
    key_env = model.upper().replace("-", "_").replace(":", "_").replace(".", "_") + "_API_KEY"
    api_key = os.environ.get(key_env, os.environ.get("CLOUD_API_KEY", ""))

    return {"model": model, "base_url": base_url, "api_key": api_key}


def case_to_diff_data(case: dict) -> dict:
    """Convert a test case YAML to the diff_data format expected by build_prompt."""
    return {
        "repo_name": "test-repo",
        "commit_hash": "0" * 40,
        "commit_date": "2024-01-01",
        "commit_message": case.get("commit_message", ""),
        "author": "test@example.com",
        "files_changed": ["test-file.md"],
        "diff_text": case.get("diff_snippet", ""),
        "stats": {},
    }


def run_single(client: OpenAI, model: str, case: dict, criteria: dict, verbose: bool = False) -> dict:
    """Run a single test case against a model. Returns result dict."""
    diff_data = case_to_diff_data(case)
    prompt = build_prompt(diff_data, criteria)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.2,
        )
        text = response.choices[0].message.content.strip()

        if verbose:
            print(f"\n--- Raw response for '{case['id']}' from {model} ---")
            print(text)
            print("---\n")

        # Extract JSON
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        result = json.loads(text)

        dims = {
            "cia": result.get("cia", {}),
            "change_nature": result.get("change_nature", "cosmetic"),
            "actionability": result.get("actionability", "none"),
            "broad_scope": result.get("broad_scope", False),
        }

        score = compute_score(dims, criteria)
        risk_level = get_risk_level(score, criteria)

        return {
            "success": True,
            "dims": dims,
            "score": score,
            "risk_level": risk_level,
            "rationale": result.get("rationale", ""),
        }

    except json.JSONDecodeError as e:
        return {"success": False, "error": f"JSON parse error: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def compare_dims(actual: dict, expected: dict) -> list[str]:
    """Compare actual dimensions to expected. Returns list of divergent dimension names."""
    divergent = []
    exp_cia = expected.get("cia", {})
    act_cia = actual.get("cia", {})

    for key in ["confidentiality", "integrity", "availability"]:
        if act_cia.get(key, False) != exp_cia.get(key, False):
            divergent.append(key[0].upper())  # C, I, or A

    if actual.get("change_nature") != expected.get("change_nature"):
        divergent.append("nature")

    if actual.get("actionability") != expected.get("actionability"):
        divergent.append("action")

    if actual.get("broad_scope", False) != expected.get("broad_scope", False):
        divergent.append("scope")

    return divergent


def format_cia(cia: dict) -> str:
    """Format CIA as compact string like '✓✓✗'."""
    c = "✓" if cia.get("confidentiality") else "✗"
    i = "✓" if cia.get("integrity") else "✗"
    a = "✓" if cia.get("availability") else "✗"
    return f"{c}{i}{a}"


def main():
    parser = argparse.ArgumentParser(description="Footnote Scorer Test Runner")
    parser.add_argument("--cases", required=True, help="Test case file or directory")
    parser.add_argument("--models", nargs="*", help="Model specs: 'model@url' (default: uses CLOUD env vars)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print raw LLM responses")
    parser.add_argument("--criteria", default=None, help="Path to scoring_criteria.yaml")
    args = parser.parse_args()

    criteria = load_criteria(args.criteria)
    cases = load_test_cases(args.cases)

    if not cases:
        print("No test cases found.")
        sys.exit(1)

    # Parse model specs
    if args.models:
        models = [parse_model_spec(m) for m in args.models]
    else:
        # Default: use env vars
        cloud_url = os.environ.get("CLOUD_OLLAMA_URL")
        cloud_model = os.environ.get("CLOUD_MODEL", "kimi-k2.5")
        cloud_key = os.environ.get("CLOUD_API_KEY", "")
        if not cloud_url:
            print("Error: No --models specified and CLOUD_OLLAMA_URL not set.")
            sys.exit(1)
        models = [{"model": cloud_model, "base_url": cloud_url, "api_key": cloud_key}]

    # Print header
    print(f"\nRunning {len(cases)} test case(s) against {len(models)} model(s)\n")
    print(f"{'Case':<40} | {'Model':<20} | {'CIA':<5} | {'Nature':<15} | {'Action':<10} | {'Scope':<5} | {'Score':<5} | {'Exp':<5} | {'Result'}")
    print("-" * 130)

    total_runs = 0
    passes = 0
    all_divergent = []

    for case in cases:
        expected = case["expected"]
        exp_dims = {
            "cia": expected["cia"],
            "change_nature": expected["change_nature"],
            "actionability": expected["actionability"],
            "broad_scope": expected["broad_scope"],
        }

        for model_spec in models:
            client = OpenAI(base_url=model_spec["base_url"], api_key=model_spec["api_key"])
            result = run_single(client, model_spec["model"], case, criteria, args.verbose)
            total_runs += 1

            case_name = case["id"][:38]
            model_name = model_spec["model"][:18]

            if not result["success"]:
                print(f"{case_name:<40} | {model_name:<20} | {'ERR':<5} | {'':<15} | {'':<10} | {'':<5} | {'':<5} | {expected['score']:<5} | FAIL: {result['error'][:40]}")
                all_divergent.append("ERROR")
                continue

            dims = result["dims"]
            divergent = compare_dims(dims, exp_dims)

            cia_str = format_cia(dims.get("cia", {}))
            nature = dims.get("change_nature", "?")[:13]
            action = dims.get("actionability", "?")[:8]
            scope = "✓" if dims.get("broad_scope") else "✗"
            score_str = f"{result['score']:.1f}"
            exp_str = f"{expected['score']:.1f}"

            if not divergent:
                status = "✓"
                passes += 1
            else:
                status = f"✗ ({','.join(divergent)})"
                all_divergent.extend(divergent)

            print(f"{case_name:<40} | {model_name:<20} | {cia_str:<5} | {nature:<15} | {action:<10} | {scope:<5} | {score_str:<5} | {exp_str:<5} | {status}")

    # Summary
    print(f"\n{'='*130}")
    print(f"Summary: {len(models)} model(s) x {len(cases)} case(s) = {total_runs} runs. "
          f"Passed: {passes}/{total_runs} ({100*passes//max(total_runs,1)}%).")

    if all_divergent:
        from collections import Counter
        counts = Counter(all_divergent)
        print(f"Divergent dimensions: {dict(counts)}")

    sys.exit(0 if passes == total_runs else 1)


if __name__ == "__main__":
    main()
