"""
Footnote Scanner — Git diff extraction and pre-filtering.

Clones/pulls documentation repos, extracts diffs from new commits,
and pre-filters noise before sending to the scorer.
"""

import json
import os
import re
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from git import Repo, GitCommandError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("footnote.scanner")


@dataclass
class RepoConfig:
    url: str
    branch: str
    name: str
    enabled: bool = True


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


def load_repos(config_path: str = "repos.json") -> list[RepoConfig]:
    """Load repository configurations."""
    with open(config_path) as f:
        data = json.load(f)
    return [RepoConfig(**r) for r in data["repos"] if r.get("enabled", True)]


def clone_or_pull(repo_config: RepoConfig, base_dir: str = "/data/repos") -> Repo:
    """Clone a repo if it doesn't exist, or pull latest changes."""
    repo_path = Path(base_dir) / repo_config.name

    if repo_path.exists() and (repo_path / ".git").exists():
        log.info(f"Pulling latest for {repo_config.name}...")
        repo = Repo(repo_path)
        origin = repo.remotes.origin
        try:
            origin.fetch()
            repo.git.reset("--hard", f"origin/{repo_config.branch}")
        except GitCommandError as e:
            log.error(f"Failed to pull {repo_config.name}: {e}")
            raise
    else:
        log.info(f"Cloning {repo_config.name} (shallow)...")
        repo_path.mkdir(parents=True, exist_ok=True)
        token = os.environ.get("GITHUB_TOKEN", "")
        url = repo_config.url
        if token and "github.com" in url:
            url = url.replace("https://", f"https://x-access-token:{token}@")
        repo = Repo.clone_from(
            url,
            repo_path,
            branch=repo_config.branch,
            depth=1,
            single_branch=True,
        )

    return repo


def get_new_commits(repo: Repo, since_hash: Optional[str] = None,
                    since_days: int = 30, max_commits: int = 500) -> list:
    """Get commits since a hash or time window."""
    if since_hash:
        try:
            # Unshallow if needed to access history
            try:
                repo.git.fetch("--unshallow")
            except GitCommandError:
                pass  # Already unshallowed

            commits = list(repo.iter_commits(f"{since_hash}..HEAD", max_count=max_commits))
            log.info(f"Found {len(commits)} new commits since {since_hash[:8]}")
            return commits
        except GitCommandError:
            log.warning(f"Hash {since_hash} not found, falling back to time-based")

    # Time-based fallback
    since_date = datetime.now(timezone.utc) - timedelta(days=since_days)
    since_str = since_date.strftime("%Y-%m-%d")

    try:
        repo.git.fetch("--unshallow")
    except GitCommandError:
        pass

    commits = list(repo.iter_commits("HEAD", since=since_str, max_count=max_commits))
    log.info(f"Found {len(commits)} commits in last {since_days} days")
    return commits


def is_noise_commit(commit) -> bool:
    """Check if a commit message indicates noise."""
    msg = commit.message.strip().split("\n")[0]  # First line only
    for pattern in NOISE_COMMIT_PATTERNS:
        if re.search(pattern, msg):
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


def extract_diff(repo: Repo, commit, max_diff_size: int = 50000) -> Optional[CommitDiff]:
    """Extract and filter diff from a single commit."""
    if is_noise_commit(commit):
        log.debug(f"Skipping noise commit: {commit.hexsha[:8]} {commit.message.strip()[:60]}")
        return None

    # Get parent (handle initial commit)
    if not commit.parents:
        return None
    parent = commit.parents[0]

    try:
        diffs = parent.diff(commit, create_patch=True)
    except Exception as e:
        log.warning(f"Failed to diff {commit.hexsha[:8]}: {e}")
        return None

    # Filter files and build diff text
    filtered_files = []
    diff_parts = []
    total_additions = 0
    total_deletions = 0

    for d in diffs:
        filepath = d.b_path or d.a_path
        if is_noise_file(filepath):
            continue

        # Only care about markdown and YAML config files
        if not filepath.endswith((".md", ".yml", ".yaml")):
            continue

        filtered_files.append(filepath)

        try:
            patch = d.diff.decode("utf-8", errors="replace")
        except Exception:
            patch = str(d.diff)

        # Count meaningful lines
        for line in patch.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                total_additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                total_deletions += 1

        diff_parts.append(f"--- {d.a_path}\n+++ {d.b_path}\n{patch}")

    # Skip if no meaningful files changed
    if not filtered_files:
        log.debug(f"Skipping commit with no meaningful files: {commit.hexsha[:8]}")
        return None

    # Skip trivial changes (< 3 meaningful lines)
    if total_additions + total_deletions < 3:
        log.debug(f"Skipping trivial commit: {commit.hexsha[:8]} (+{total_additions}/-{total_deletions})")
        return None

    diff_text = "\n".join(diff_parts)

    # Truncate if too large
    if len(diff_text) > max_diff_size:
        diff_text = diff_text[:max_diff_size] + "\n\n[... truncated ...]"

    return CommitDiff(
        repo_name="",  # Set by caller
        commit_hash=commit.hexsha,
        commit_date=datetime.fromtimestamp(commit.committed_date, tz=timezone.utc).isoformat(),
        commit_message=commit.message.strip(),
        author=str(commit.author),
        files_changed=filtered_files,
        diff_text=diff_text,
        stats={
            "additions": total_additions,
            "deletions": total_deletions,
            "files": len(filtered_files),
        },
    )


def scan_repo(repo_config: RepoConfig, since_hash: Optional[str] = None,
              since_days: int = 30, base_dir: str = "/data/repos") -> list[CommitDiff]:
    """Full scan pipeline for a single repo."""
    log.info(f"=== Scanning {repo_config.name} ===")

    repo = clone_or_pull(repo_config, base_dir)
    commits = get_new_commits(repo, since_hash=since_hash, since_days=since_days)

    results = []
    skipped = 0

    for commit in commits:
        diff = extract_diff(repo, commit)
        if diff:
            diff.repo_name = repo_config.name
            results.append(diff)
        else:
            skipped += 1

    log.info(f"Extracted {len(results)} meaningful diffs, skipped {skipped}")
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Footnote Scanner")
    parser.add_argument("--config", default="repos.json", help="Repo config file")
    parser.add_argument("--data-dir", default="/data/repos", help="Base dir for cloned repos")
    parser.add_argument("--since-days", type=int, default=30, help="Backfill window in days")
    parser.add_argument("--output", default="-", help="Output file (- for stdout)")
    args = parser.parse_args()

    repos = load_repos(args.config)
    all_diffs = []

    for rc in repos:
        diffs = scan_repo(rc, since_days=args.since_days, base_dir=args.data_dir)
        all_diffs.extend(diffs)

    output = json.dumps([asdict(d) for d in all_diffs], indent=2, default=str)

    if args.output == "-":
        print(output)
    else:
        with open(args.output, "w") as f:
            f.write(output)
        log.info(f"Wrote {len(all_diffs)} diffs to {args.output}")
