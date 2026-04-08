"""
Footnote Scanner — GitHub API-based diff extraction and pre-filtering.

Uses the GitHub REST API instead of git clone to avoid downloading
massive repos. Fetches commit lists and diffs directly.
"""

import json
import os
import re
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("footnote.scanner")


@dataclass
class RepoConfig:
    url: str
    branch: str
    name: str
    enabled: bool = True

    @property
    def owner_repo(self) -> str:
        """Extract 'owner/repo' from GitHub URL."""
        # https://github.com/MicrosoftDocs/azure-docs -> MicrosoftDocs/azure-docs
        parts = self.url.rstrip("/").split("/")
        return f"{parts[-2]}/{parts[-1]}"


@dataclass
class CommitDiff:
    """A single commit's extracted diff data."""
    repo_name: str
    commit_hash: str
    commit_date: str
    commit_message: str
    author: str
    files_changed: list[str]
    diff_text: str
    stats: dict = field(default_factory=dict)


# --- Noise filters ---

# File patterns to skip entirely
SKIP_PATTERNS = [
    r"\.(?:png|jpg|jpeg|gif|svg|ico|bmp|webp)$",     # Images
    r"\.(?:pdf|zip|tar|gz)$",                          # Binaries
    r"/includes/",                                      # Shared includes (usually boilerplate)
    r"bread-toc\.yml$",                                 # TOC files
    r"zone-pivot-groups\.yml$",                         # Zone pivots
    r"\.openpublishing\.",                              # Publishing config
]

# Locale/translation directories
LOCALE_PATTERNS = [
    r"/(?:cs-cz|de-de|es-es|fr-fr|hu-hu|id-id|it-it|ja-jp|ko-kr|nl-nl|pl-pl|pt-br|pt-pt|ru-ru|sv-se|tr-tr|zh-cn|zh-tw)/",
]

# Commit message patterns that indicate noise
NOISE_COMMIT_PATTERNS = [
    r"^Merge\s+(?:pull\s+request|branch)",
    r"^Update\s+\S+\.md$",                             # Single-file title-only updates
    r"(?i)fix(?:ed)?\s+(?:typo|spelling|grammar|formatting|whitespace|broken\s+link)",
    r"(?i)^locale\b",
    r"(?i)^revert\b.*revert\b",                        # Revert of a revert
]


class GitHubAPI:
    """Lightweight GitHub REST API client."""

    BASE = "https://api.github.com"

    def __init__(self, token: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/vnd.github.v3+json"
        self.session.headers["User-Agent"] = "footnote-scanner/0.1"
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.rate_remaining = 5000
        self.rate_reset = 0

    def _request(self, endpoint: str, **kwargs) -> Optional[dict | list]:
        """Make a rate-limit-aware API request."""
        if self.rate_remaining < 10:
            wait = max(0, self.rate_reset - time.time()) + 1
            log.warning(f"Rate limit low ({self.rate_remaining}), sleeping {wait:.0f}s")
            time.sleep(wait)

        url = f"{self.BASE}{endpoint}" if endpoint.startswith("/") else endpoint
        resp = self.session.get(url, **kwargs)

        # Update rate limit info
        self.rate_remaining = int(resp.headers.get("X-RateLimit-Remaining", 5000))
        self.rate_reset = int(resp.headers.get("X-RateLimit-Reset", 0))

        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 422:
            log.warning(f"GitHub API 422 for {endpoint}: {resp.text[:200]}")
            return None
        elif resp.status_code in (403, 429):
            wait = max(0, self.rate_reset - time.time()) + 5
            log.warning(f"Rate limited, sleeping {wait:.0f}s")
            time.sleep(wait)
            return self._request(endpoint, **kwargs)
        else:
            log.error(f"GitHub API {resp.status_code}: {resp.text[:200]}")
            return None

    def list_commits(self, owner_repo: str, since: str,
                     branch: str = "main", per_page: int = 100,
                     max_pages: int = 10) -> list[dict]:
        """List commits since a date. Returns list of commit objects."""
        commits = []
        page = 1

        while page <= max_pages:
            data = self._request(
                f"/repos/{owner_repo}/commits",
                params={
                    "sha": branch,
                    "since": since,
                    "per_page": per_page,
                    "page": page,
                }
            )
            if not data:
                break

            commits.extend(data)

            if len(data) < per_page:
                break
            page += 1

        return commits

    def get_commit(self, owner_repo: str, sha: str) -> Optional[dict]:
        """Get a single commit with diff/patch info."""
        return self._request(f"/repos/{owner_repo}/commits/{sha}")


def load_repos(config_path: str = "repos.json") -> list[RepoConfig]:
    """Load repository configurations."""
    with open(config_path) as f:
        data = json.load(f)
    return [RepoConfig(**r) for r in data["repos"] if r.get("enabled", True)]


def is_noise_commit(message: str) -> bool:
    """Check if a commit message indicates noise."""
    first_line = message.strip().split("\n")[0]
    for pattern in NOISE_COMMIT_PATTERNS:
        if re.search(pattern, first_line):
            return True
    return False


def is_noise_file(filepath: str) -> bool:
    """Check if a file path should be skipped."""
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, filepath, re.IGNORECASE):
            return True
    for pattern in LOCALE_PATTERNS:
        if re.search(pattern, filepath):
            return True
    return False


def extract_commit_diff(api: GitHubAPI, owner_repo: str,
                        commit_summary: dict, max_diff_size: int = 50000) -> Optional[CommitDiff]:
    """Extract and filter diff from a single commit via GitHub API."""
    sha = commit_summary["sha"]
    message = commit_summary["commit"]["message"]
    author = commit_summary["commit"]["author"]["name"]
    date = commit_summary["commit"]["author"]["date"]

    if is_noise_commit(message):
        log.debug(f"Skipping noise commit: {sha[:8]} {message[:60]}")
        return None

    # Fetch full commit with file diffs
    detail = api.get_commit(owner_repo, sha)
    if not detail or "files" not in detail:
        return None

    filtered_files = []
    diff_parts = []
    total_additions = 0
    total_deletions = 0

    for f in detail["files"]:
        filepath = f["filename"]
        if is_noise_file(filepath):
            continue
        if not filepath.endswith((".md", ".yml", ".yaml")):
            continue

        filtered_files.append(filepath)
        total_additions += f.get("additions", 0)
        total_deletions += f.get("deletions", 0)

        patch = f.get("patch", "")
        if patch:
            diff_parts.append(f"--- {filepath}\n+++ {filepath}\n{patch}")

    # Skip if no meaningful files changed
    if not filtered_files:
        return None

    # Skip trivial changes (< 3 meaningful lines)
    if total_additions + total_deletions < 3:
        log.debug(f"Skipping trivial commit: {sha[:8]} (+{total_additions}/-{total_deletions})")
        return None

    diff_text = "\n".join(diff_parts)
    if len(diff_text) > max_diff_size:
        diff_text = diff_text[:max_diff_size] + "\n\n[... truncated ...]"

    return CommitDiff(
        repo_name="",  # Set by caller
        commit_hash=sha,
        commit_date=date,
        commit_message=message.strip(),
        author=author,
        files_changed=filtered_files,
        diff_text=diff_text,
        stats={
            "additions": total_additions,
            "deletions": total_deletions,
            "files": len(filtered_files),
        },
    )


def scan_repo(repo_config: RepoConfig, since_hash: Optional[str] = None,
              since_days: int = 30, token: Optional[str] = None) -> list[CommitDiff]:
    """Full scan pipeline for a single repo using GitHub API."""
    log.info(f"=== Scanning {repo_config.name} ===")

    api = GitHubAPI(token=token)
    owner_repo = repo_config.owner_repo

    # Determine since date
    since_date = datetime.now(timezone.utc) - timedelta(days=since_days)
    since_str = since_date.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Get commit list
    log.info(f"Fetching commits since {since_str}...")
    commits = api.list_commits(owner_repo, since=since_str, branch=repo_config.branch)
    log.info(f"Found {len(commits)} commits")

    # If we have a since_hash, skip commits we've already seen
    if since_hash:
        new_commits = []
        for c in commits:
            if c["sha"] == since_hash:
                break
            new_commits.append(c)
        commits = new_commits
        log.info(f"After filtering since {since_hash[:8]}: {len(commits)} new commits")

    results = []
    skipped = 0

    for i, commit_summary in enumerate(commits):
        if i % 50 == 0 and i > 0:
            log.info(f"Progress: {i}/{len(commits)} commits processed, {len(results)} diffs extracted")

        diff = extract_commit_diff(api, owner_repo, commit_summary)
        if diff:
            diff.repo_name = repo_config.name
            results.append(diff)
        else:
            skipped += 1

        # Respect rate limits — small delay between commit detail fetches
        if i % 30 == 0 and i > 0:
            log.info(f"Rate limit remaining: {api.rate_remaining}")
            if api.rate_remaining < 100:
                time.sleep(2)

    log.info(f"Extracted {len(results)} meaningful diffs, skipped {skipped}")
    return results


def get_head_sha(repo_config: RepoConfig, token: Optional[str] = None) -> Optional[str]:
    """Get the current HEAD SHA for a repo branch."""
    api = GitHubAPI(token=token)
    data = api._request(f"/repos/{repo_config.owner_repo}/commits/{repo_config.branch}")
    return data["sha"] if data else None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Footnote Scanner")
    parser.add_argument("--config", default="repos.json", help="Repo config file")
    parser.add_argument("--since-days", type=int, default=30, help="Backfill window in days")
    parser.add_argument("--output", default="-", help="Output file (- for stdout)")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"), help="GitHub token")
    args = parser.parse_args()

    repos = load_repos(args.config)
    all_diffs = []

    for rc in repos:
        diffs = scan_repo(rc, since_days=args.since_days, token=args.token)
        all_diffs.extend(diffs)

    output = json.dumps([asdict(d) for d in all_diffs], indent=2, default=str)

    if args.output == "-":
        print(output)
    else:
        with open(args.output, "w") as f:
            f.write(output)
        log.info(f"Wrote {len(all_diffs)} diffs to {args.output}")
