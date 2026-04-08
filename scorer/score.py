"""
Footnote Scorer — LLM-based security relevance scoring.

Tiered pipeline:
  Tier 1: Local model (Gemma) for quick pre-filter (score 0-10)
  Tier 2: Cloud model for detailed analysis on high-signal diffs
"""

import json
import os
import logging
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("footnote.scorer")

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
]

SCORING_PROMPT = """You are a security analyst reviewing changes to cloud documentation (e.g., Azure, AWS, GCP docs).

Your job: assess how security-relevant this documentation change is.

**Scoring (0-10):**
- 0-2: No security relevance (formatting, typos, cosmetic)
- 3-4: Minor relevance (new features mentioned, minor config changes)
- 5-6: Moderate relevance (default behavior changes, permission updates)
- 7-8: High relevance (breaking auth changes, new security features, deprecations affecting security)
- 9-10: Critical (silent security fixes, major permission model changes, default encryption changes)

**Tags** (pick all that apply from this list):
{tags}

**Respond in this exact JSON format and nothing else:**
```json
{{
  "score": <0-10>,
  "risk_level": "<informational|low|medium|high|critical>",
  "tags": ["tag1", "tag2"],
  "summary": "<2-3 sentence plain English summary of what changed and why it matters for security>",
  "services": ["<affected Azure/cloud services>"]
}}
```

**Commit:** {commit_hash}
**Date:** {commit_date}
**Message:** {commit_message}
**Files changed:** {files_changed}

**Diff:**
```
{diff_text}
```
"""

PREFILTER_PROMPT = """Rate the security relevance of this documentation change from 0-10.
0 = no security relevance, 10 = critical security change.
Reply with ONLY a single integer.

Commit: {commit_message}
Files: {files_changed}

Diff (first 2000 chars):
{diff_preview}
"""


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
        # Extract integer from response
        score = int("".join(c for c in text if c.isdigit())[:2])
        return min(max(score, 0), 10)
    except Exception as e:
        log.warning(f"Prefilter failed for {diff_data['commit_hash'][:8]}: {e}")
        return 5  # Default to medium on failure (don't skip)


def full_score(client: OpenAI, model: str, diff_data: dict) -> Optional[ScoredChange]:
    """Detailed security scoring using cloud model."""
    # Truncate diff for context window
    diff_text = diff_data["diff_text"]
    if len(diff_text) > 15000:
        diff_text = diff_text[:15000] + "\n\n[... truncated ...]"

    prompt = SCORING_PROMPT.format(
        tags=", ".join(VALID_TAGS),
        commit_hash=diff_data["commit_hash"][:12],
        commit_date=diff_data["commit_date"],
        commit_message=diff_data["commit_message"][:500],
        files_changed=", ".join(diff_data["files_changed"][:20]),
        diff_text=diff_text,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.2,
        )
        text = response.choices[0].message.content.strip()

        # Extract JSON from response (handle markdown code blocks)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        result = json.loads(text)

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
            score=min(max(float(result.get("score", 0)), 0), 10),
            risk_level=result.get("risk_level", "informational"),
            tags=valid_tags,
            summary=result.get("summary", ""),
            services=result.get("services", []),
        )
    except json.JSONDecodeError as e:
        log.error(f"JSON parse error for {diff_data['commit_hash'][:8]}: {e}\nRaw: {text[:500]}")
        return None
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
    Tier 2: Cloud model full scoring (detailed, costs money)
    """
    results = []
    prefiltered = 0
    scored = 0
    failed = 0

    # Set up clients
    use_prefilter = local_url is not None
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
    from dataclasses import asdict

    parser = argparse.ArgumentParser(description="Footnote Scorer")
    parser.add_argument("--input", required=True, help="Input JSON file from scanner")
    parser.add_argument("--output", default="-", help="Output file (- for stdout)")
    parser.add_argument("--local-url", default=os.environ.get("GEMMA_URL"), help="Local LLM URL")
    parser.add_argument("--local-model", default="gemma4:26b")
    parser.add_argument("--cloud-url", default=os.environ.get("CLOUD_BASE_URL"), help="Cloud LLM URL")
    parser.add_argument("--cloud-model", default=os.environ.get("CLOUD_MODEL", "kimi-k2.5:cloud"))
    parser.add_argument("--cloud-key", default=os.environ.get("CLOUD_API_KEY"))
    parser.add_argument("--threshold", type=int, default=3, help="Pre-filter threshold")
    args = parser.parse_args()

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
