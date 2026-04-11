"""Quick script to run test cases against Claude Opus 4.6 via local Anthropic proxy."""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

from score import load_criteria, build_prompt, compute_score, get_risk_level

CASES_DIR = Path(__file__).parent / "test_cases"


def load_test_cases():
    cases = []
    for f in sorted(CASES_DIR.glob("*.yaml")):
        with open(f) as fh:
            cases.append(yaml.safe_load(fh))
    return cases


def case_to_diff_data(case):
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


def call_claude(base_url, auth_token, prompt):
    """Call Claude via native Anthropic streaming API using bash curl (Windows Python subprocess has SSE buffering issues)."""
    import subprocess, tempfile

    payload = json.dumps({
        "model": "claude-opus-4-6",
        "max_tokens": 4000,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    })

    # Write payload to temp file
    payload_file = os.path.join(os.path.dirname(__file__), "_payload.json").replace("\\", "/")
    result_file = os.path.join(os.path.dirname(__file__), "_result.txt").replace("\\", "/")
    with open(payload_file, "w", encoding="utf-8") as f:
        f.write(payload)

    try:
        # Use bash to run curl (Python subprocess + curl has SSE buffering issues on Windows)
        bash_cmd = (
            f'curl -s -X POST "{base_url}/v1/messages" '
            f'-H "Authorization: Bearer {auth_token}" '
            f'-H "Content-Type: application/json" '
            f'-H "anthropic-version: 2023-06-01" '
            f'-d @{payload_file} > {result_file}'
        )
        subprocess.run(
            ["bash", "-c", bash_cmd],
            timeout=120, check=True,
        )
        with open(result_file, "r", encoding="utf-8") as f:
            raw = f.read()
    finally:
        if os.path.exists(payload_file):
            os.unlink(payload_file)
        if os.path.exists(result_file):
            os.unlink(result_file)

    # Parse SSE events to extract text content
    text_parts = []
    for line in raw.split("\n"):
        if line.startswith("data: "):
            try:
                data = json.loads(line[6:])
                if data.get("type") == "content_block_delta":
                    delta = data.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text_parts.append(delta.get("text", ""))
            except json.JSONDecodeError:
                pass

    return "".join(text_parts).strip()


def main():
    criteria = load_criteria()
    cases = load_test_cases()

    base_url = os.environ["ANTHROPIC_BASE_URL"]
    auth_token = os.environ["ANTHROPIC_AUTH_TOKEN"]

    print(f"\nRunning {len(cases)} test cases against claude-opus-4-6\n")
    print(f"{'Case':<42} | {'Score':>5} | {'Expected':>8} | {'Diff':>5} | Result")
    print("-" * 85)

    total = 0
    exact = 0
    total_diff = 0
    results = {}

    for case in cases:
        case_id = case["id"]
        expected = case["expected"]
        diff_data = case_to_diff_data(case)
        prompt = build_prompt(diff_data, criteria)

        try:
            text = call_claude(base_url, auth_token, prompt)

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
            exp_score = expected["score"]
            diff = score - exp_score
            total += 1
            total_diff += abs(diff)

            if abs(diff) < 0.01:
                exact += 1
                status = "✓"
            else:
                status = f"✗ ({diff:+.1f})"

            results[case_id] = {"score": score, "diff": diff}
            print(f"{case_id:<42} | {score:>5.1f} | {exp_score:>8.1f} | {diff:>+5.1f} | {status}")

        except Exception as e:
            total += 1
            results[case_id] = {"score": None, "error": str(e)}
            print(f"{case_id:<42} | {'ERR':>5} | {expected['score']:>8.1f} | {'':>5} | FAIL: {str(e)[:50]}")

    print(f"\n{'=' * 85}")
    avg_diff = total_diff / max(total, 1)
    print(f"Exact match: {exact}/{total} ({100 * exact // max(total, 1)}%)")
    print(f"Avg score diff: {avg_diff:.1f}")
    print(f"\nResults JSON:")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
