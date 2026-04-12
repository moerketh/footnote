"""
Footnote Scorer — Structured, explainable security relevance scoring.

Tiered pipeline:
  Tier 1: Local model (Gemma) for quick pre-filter (score 0-10)
  Tier 2: Cloud model for structured dimension classification
  Score: Computed deterministically from dimensions (not by LLM)
"""

import json
import os
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import yaml
from openai import OpenAI, RateLimitError, APIStatusError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("footnote.scorer")

SCORER_DIR = Path(__file__).parent

# Tags we assign to changes
VALID_TAGS = [
    "permission-change",
    "default-behavior",
    "deprecation",
    "new-security-feature",
    "auth-change",
    "network-change",
    "encryption",
    "compliance",
    "api-breaking",
    "silent-fix",
    "identity",
    "monitoring",
    "deadline-imminent",
    "deadline-future",
]

PREFILTER_PROMPT = """Rate the security relevance of this documentation change from 0-10.
0 = no security relevance, 10 = critical security change.
Reply with ONLY a single integer.

Commit: {commit_message}
Files: {files_changed}

Diff (first 2000 chars):
{diff_preview}
"""

# Module-level cache for criteria
_criteria_cache = None


def load_criteria(path: Optional[str] = None) -> dict:
    """Load scoring criteria from YAML. Cached after first call."""
    global _criteria_cache
    if _criteria_cache is not None:
        return _criteria_cache

    if path is None:
        path = SCORER_DIR / "scoring_criteria.yaml"
    with open(path) as f:
        _criteria_cache = yaml.safe_load(f)
    return _criteria_cache


def get_max_points(criteria: dict) -> float:
    """Calculate maximum possible raw points from criteria dimensions."""
    total = 0
    for dim in criteria["dimensions"]:
        if dim["type"] == "boolean":
            total += dim["points"]
        elif dim["type"] == "enum":
            total += max(level["points"] for level in dim["levels"].values())
    return total


def resolve_points(dims: dict, dimension: dict) -> float:
    """Resolve points for a single dimension from LLM output."""
    name = dimension["name"]
    group = dimension.get("group")

    if dimension["type"] == "boolean":
        if group == "cia":
            value = dims.get("cia", {}).get(name, False)
        else:
            value = dims.get(name, False)
        return dimension["points"] if value else 0

    elif dimension["type"] == "enum":
        value = dims.get(name, list(dimension["levels"].keys())[0])
        level = dimension["levels"].get(value)
        if level is None:
            log.warning(f"Unknown level '{value}' for dimension '{name}', defaulting to 0")
            return 0
        return level["points"]

    return 0


def normalize_broad_scope(value) -> str:
    """Normalize broad_scope from bool (legacy) or string to enum value."""
    if isinstance(value, bool):
        return "existing" if value else "none"
    if isinstance(value, str) and value in ("none", "new_only", "existing"):
        return value
    return "none"


def compute_score(dims: dict, criteria: Optional[dict] = None) -> float:
    """
    Compute score deterministically from dimension classifications.
    Normalizes raw points to 0-10 scale.
    """
    if criteria is None:
        criteria = load_criteria()

    raw = 0
    max_possible = get_max_points(criteria)

    for dimension in criteria["dimensions"]:
        raw += resolve_points(dims, dimension)

    return round(raw / max_possible * 10, 1)


def get_risk_level(score: float, criteria: Optional[dict] = None) -> str:
    """Determine risk level from score using criteria thresholds."""
    if criteria is None:
        criteria = load_criteria()

    for threshold in criteria["risk_thresholds"]:
        if "max" in threshold and score <= threshold["max"]:
            return threshold["level"]
        if "above" in threshold and score > threshold["above"]:
            return threshold["level"]
    return "informational"


def load_examples(n: int = 2) -> str:
    """Load few-shot examples from test_cases/ for prompt injection."""
    cases_dir = SCORER_DIR / "test_cases"
    if not cases_dir.exists():
        return ""

    examples = []
    case_files = sorted(cases_dir.glob("*.yaml"))

    # Pick a high-scoring and low-scoring example for contrast
    high = None
    low = None
    for f in case_files:
        with open(f) as fh:
            case = yaml.safe_load(fh)
        score = case["expected"]["score"]
        if score >= 8 and high is None:
            high = case
        elif score <= 1 and low is None:
            low = case

    selected = [c for c in [high, low] if c is not None][:n]

    for case in selected:
        exp = case["expected"]
        example_json = json.dumps({
            "cia": exp["cia"],
            "change_nature": exp["change_nature"],
            "actionability": exp["actionability"],
            "broad_scope": exp["broad_scope"],
            "rationale": exp["rationale"],
            "summary": exp["rationale"],  # simplified for example
            "tags": [],
            "services": [],
        }, indent=2)
        examples.append(f"### {case['title']}\nDiff:\n```\n{case['diff_snippet'].strip()}\n```\nOutput:\n```json\n{example_json}\n```")

    return "\n\n".join(examples)


def format_criteria_for_prompt(criteria: dict) -> str:
    """Format criteria dimensions as human-readable text for the prompt."""
    lines = []
    for dim in criteria["dimensions"]:
        if dim["type"] == "boolean":
            group_prefix = f"({dim['group'].upper()}) " if dim.get("group") else ""
            lines.append(f"- **{group_prefix}{dim['name']}** (true/false, +{dim['points']} point): {dim['description']}")
        elif dim["type"] == "enum":
            lines.append(f"- **{dim['name']}** (choose one):")
            for level_name, level_def in dim["levels"].items():
                lines.append(f"  - `{level_name}` (+{level_def['points']}): {level_def['description']}")

    if criteria.get("notes"):
        lines.append("\n**Important notes:**")
        for note in criteria["notes"]:
            lines.append(f"- {note}")

    return "\n".join(lines)


def build_prompt(diff_data: dict, criteria: Optional[dict] = None) -> str:
    """Build the full scoring prompt from template + criteria + examples."""
    if criteria is None:
        criteria = load_criteria()

    template_path = SCORER_DIR / "prompt_template.md"
    with open(template_path) as f:
        template = f.read()

    criteria_text = format_criteria_for_prompt(criteria)
    examples_text = load_examples(n=2)

    repo_desc = diff_data.get("repo_description", "")
    repo_desc_line = f"Context: {repo_desc}\n" if repo_desc else ""

    # Signal-based truncation — see MODELS.md "Scoring Approach" for rationale.
    return template.format(
        criteria=criteria_text,
        examples=examples_text,
        repo_name=diff_data.get("repo_name", "unknown"),
        repo_description=repo_desc_line,
        commit_hash=diff_data.get("commit_hash", "")[:12],
        author=diff_data.get("author", "unknown"),
        commit_date=diff_data.get("commit_date", ""),
        commit_message=diff_data.get("commit_message", "")[:500],
        files_changed=", ".join(diff_data.get("files_changed", [])[:20]),
        diff_text=diff_data.get("diff_text", "")[:8000],
        tags=", ".join(VALID_TAGS),
    )


@dataclass
class ScoredChange:
    """A scored documentation change."""
    repo_name: str
    commit_hash: str
    commit_date: str
    commit_message: str
    author: str
    files_changed: list[str]
    diff_text: str
    stats: dict
    score: float
    risk_level: str
    tags: list[str]
    summary: str
    services: list[str]
    rationale: str = ""
    scoring_details: dict = field(default_factory=dict)
    scored_by: str = ""


def get_client(base_url: str, api_key: str) -> OpenAI:
    """Create an OpenAI-compatible client."""
    return OpenAI(base_url=base_url, api_key=api_key)


def prefilter_score(client: OpenAI, model: str, diff_data: dict) -> int:
    """Quick pre-filter score using local model. Returns 0-10."""
    prompt = PREFILTER_PROMPT.format(
        commit_message=diff_data["commit_message"][:200],
        files_changed=", ".join(diff_data["files_changed"][:10]),
        diff_preview=diff_data["diff_text"][:2000],
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.1,
        )
        text = response.choices[0].message.content.strip()
        score = int("".join(c for c in text if c.isdigit())[:2])
        return min(max(score, 0), 10)
    except Exception as e:
        log.warning(f"Prefilter failed for {diff_data['commit_hash'][:8]}: {e}")
        return 5  # Default to medium on failure (don't skip)


def full_score(client: OpenAI, model: str, diff_data: dict) -> Optional[ScoredChange]:
    """Structured security scoring using cloud model."""
    criteria = load_criteria()
    prompt = build_prompt(diff_data, criteria)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.2,
        )
        text = response.choices[0].message.content.strip()

        # Extract JSON from response (handle markdown code blocks)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        result = json.loads(text)

        # Extract dimensions for deterministic scoring
        dims = {
            "cia": result.get("cia", {}),
            "change_nature": result.get("change_nature", "cosmetic"),
            "actionability": result.get("actionability", "none"),
            "broad_scope": normalize_broad_scope(result.get("broad_scope", "none")),
        }

        # Compute score deterministically
        score = compute_score(dims, criteria)
        risk_level = get_risk_level(score, criteria)

        # Validate tags
        valid_tags = [t for t in result.get("tags", []) if t in VALID_TAGS]

        return ScoredChange(
            repo_name=diff_data["repo_name"],
            commit_hash=diff_data["commit_hash"],
            commit_date=diff_data["commit_date"],
            commit_message=diff_data["commit_message"],
            author=diff_data["author"],
            files_changed=diff_data["files_changed"],
            diff_text=diff_data["diff_text"],
            stats=diff_data["stats"],
            score=score,
            risk_level=risk_level,
            tags=valid_tags,
            summary=result.get("summary", ""),
            services=result.get("services", []),
            rationale=result.get("rationale", ""),
            scoring_details=dims,
            scored_by=model,
        )
    except json.JSONDecodeError as e:
        log.error(f"JSON parse error for {diff_data['commit_hash'][:8]}: {e}\nRaw: {text[:500]}")
        return None
    except (RateLimitError, APIStatusError) as e:
        # Surface rate limit and server errors so the pipeline can handle them
        raise
    except Exception as e:
        log.error(f"Scoring failed for {diff_data['commit_hash'][:8]}: {e}")
        return None


def score_diffs(diffs: list[dict],
                prefilter_threshold: int = 3,
                local_url: Optional[str] = None,
                local_model: str = "gemma4:26b",
                local_key: str = "ollama",
                cloud_url: Optional[str] = None,
                cloud_model: str = "kimi-k2.5:cloud",
                cloud_key: Optional[str] = None) -> list[ScoredChange]:
    """
    Tiered scoring pipeline.

    Tier 1: Local model pre-filter (fast, free)
    Tier 2: Cloud model structured classification (detailed, costs money)
    Score: Deterministic computation from classified dimensions
    """
    results = []
    prefiltered = 0
    scored = 0
    failed = 0

    # Set up clients
    use_prefilter = bool(local_url)
    if use_prefilter:
        local_client = get_client(local_url, local_key)

    if not cloud_url:
        log.error("No cloud scoring URL configured")
        return results

    cloud_client = get_client(cloud_url, cloud_key or "")

    for diff_data in diffs:
        # Tier 1: Pre-filter
        if use_prefilter:
            pre_score = prefilter_score(local_client, local_model, diff_data)
            if pre_score < prefilter_threshold:
                prefiltered += 1
                log.debug(f"Pre-filtered {diff_data['commit_hash'][:8]} (score={pre_score})")
                continue

        # Tier 2: Full scoring
        result = full_score(cloud_client, cloud_model, diff_data)
        if result:
            results.append(result)
            scored += 1
            log.info(f"Scored {result.commit_hash[:8]}: {result.score}/10 [{result.risk_level}] {result.tags}")
        else:
            failed += 1

    log.info(f"Scoring complete: {scored} scored, {prefiltered} pre-filtered, {failed} failed")
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Footnote Scorer")
    parser.add_argument("--input", help="Input JSON file from scanner")
    parser.add_argument("--output", default="-", help="Output file (- for stdout)")
    parser.add_argument("--local-url", default=os.environ.get("LOCAL_OLLAMA_URL"), help="Local Ollama URL (OpenAI-compatible)")
    parser.add_argument("--local-model", default="gemma4:26b")
    parser.add_argument("--cloud-url", default=os.environ.get("CLOUD_OLLAMA_URL"), help="Cloud Ollama URL (OpenAI-compatible)")
    parser.add_argument("--cloud-model", default=os.environ.get("CLOUD_MODEL", "kimi-k2.5"))
    parser.add_argument("--cloud-key", default=os.environ.get("CLOUD_API_KEY"))
    parser.add_argument("--threshold", type=int, default=3, help="Pre-filter threshold")
    args = parser.parse_args()

    if not args.input:
        parser.error("--input is required")

    with open(args.input) as f:
        diffs = json.load(f)

    results = score_diffs(
        diffs,
        prefilter_threshold=args.threshold,
        local_url=args.local_url,
        local_model=args.local_model,
        cloud_url=args.cloud_url,
        cloud_model=args.cloud_model,
        cloud_key=args.cloud_key,
    )

    output = json.dumps([asdict(r) for r in results], indent=2, default=str)

    if args.output == "-":
        print(output)
    else:
        with open(args.output, "w") as f:
            f.write(output)
        log.info(f"Wrote {len(results)} scored changes to {args.output}")
