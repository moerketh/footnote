"""
Footnote Scanner — Git-based diff extraction and pre-filtering.

Clones repos with sufficient depth for backfill, then uses local git
for fast diff extraction. No unshallowing needed.
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
    description: str = ""


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

SKIP_PATTERNS = [
    r"\.(?:png|jpg|jpeg|gif|svg|ico|bmp|webp)$",
    r"\.(?:pdf|zip|tar|gz)$",
    r"bread-toc\.yml$",
    r"zone-pivot-groups\.yml$",
    r"\.openpublishing\.",
]

LOCALE_PATTERNS = [
    r"/(?:cs-cz|de-de|es-es|fr-fr|hu-hu|id-id|it-it|ja-jp|ko-kr|nl-nl|pl-pl|pt-br|pt-pt|ru-ru|sv-se|tr-tr|zh-cn|zh-tw)/",
]

NOISE_COMMIT_PATTERNS = [
    # Only matches standard merge commits ("Merge pull request #123 from ..."),
    # NOT squash merges (which use the PR title as commit message).
    # Standard merges are noise because individual commits are in the history.
    # Squash merges are the sole record of PR changes and must be scored.
    r"^Merge\s+(?:pull\s+request|branch)",
    r"(?i)fix(?:ed)?\s+(?:typo|spelling|grammar|formatting|whitespace|broken\s+link)",
    r"(?i)^locale\b",
    # only catches double-reverts (revert of a revert), not single reverts which could be security-relevant
    r"(?i)^revert\b.*revert\b",
]


def load_repos(config_path: str = "repos.json") -> list[RepoConfig]:
    """Load repository configurations."""
    with open(config_path) as f:
        data = json.load(f)
    return [RepoConfig(**r) for r in data["repos"] if r.get("enabled", True)]


def clone_or_pull(repo_config: RepoConfig, base_dir: str = "/data/repos",
                  depth: int = 6000) -> Repo:
    """
    Clone a repo with sufficient depth, or pull latest.
    
    Uses --depth=N on initial clone (NOT depth=1 + unshallow).
    Subsequent runs just fetch new commits — fast and cheap.
    """
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
        log.info(f"Cloning {repo_config.name} (depth={depth})...")
        log.info("Initial clone may take several minutes for large repos.")
        repo_path.mkdir(parents=True, exist_ok=True)
        token = os.environ.get("GITHUB_TOKEN", "")
        url = repo_config.url
        if token and "github.com" in url:
            url = url.replace("https://", f"https://x-access-token:{token}@")
        repo = Repo.clone_from(
            url,
            repo_path,
            branch=repo_config.branch,
            depth=depth,
            single_branch=True,
            no_tags=True,
        )
        log.info(f"Clone complete: {repo_path}")

    return repo


def get_new_commits(repo: Repo, since_hash: Optional[str] = None,
                    since_days: int = 30) -> list:
    """
    Get commits since a hash or time window.

    No max_commits cap — scanning is cheap (local git). The expensive LLM
    scoring step uses has_change() to skip already-processed commits.
    """
    if since_hash:
        try:
            commits = list(repo.iter_commits(f"{since_hash}..HEAD"))
            log.info(f"Found {len(commits)} new commits since {since_hash[:8]}")
            return commits
        except GitCommandError:
            log.warning(f"Hash {since_hash} not found in shallow history, falling back to time-based")

    # Time-based fallback
    since_date = datetime.now(timezone.utc) - timedelta(days=since_days)
    since_str = since_date.strftime("%Y-%m-%d")
    commits = list(repo.iter_commits("HEAD", since=since_str))
    log.info(f"Found {len(commits)} commits in last {since_days} days")
    return commits


def is_noise_commit(commit) -> bool:
    """Check if a commit message indicates noise."""
    msg = commit.message.strip().split("\n")[0]
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
        return None

    if not commit.parents:
        return None
    parent = commit.parents[0]

    try:
        diffs = parent.diff(commit, create_patch=True)
    except Exception as e:
        log.warning(f"Failed to diff {commit.hexsha[:8]}: {e}")
        return None

    filtered_files = []
    diff_parts = []
    total_additions = 0
    total_deletions = 0
    all_added_lines = []
    all_removed_lines = []

    for d in diffs:
        filepath = d.b_path or d.a_path
        if is_noise_file(filepath):
            continue
        if not filepath.endswith((".md", ".yml", ".yaml")):
            continue

        filtered_files.append(filepath)

        try:
            patch = d.diff.decode("utf-8", errors="replace")
        except Exception:
            patch = str(d.diff)

        for line in patch.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                total_additions += 1
                all_added_lines.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                total_deletions += 1
                all_removed_lines.append(line[1:])

        diff_parts.append(f"--- {d.a_path}\n+++ {d.b_path}\n{patch}")

    if not filtered_files:
        return None

    # Any non-empty diff reaches the scorer — even a single added line
    # could be security-relevant (e.g. a new permission requirement note)
    if total_additions + total_deletions < 1:
        return None

    # Skip punctuation/capitalization-only changes: if stripping non-alphanumeric
    # chars and lowercasing makes added and removed lines identical, it's just formatting
    if total_additions + total_deletions <= 4:
        strip = lambda s: re.sub(r"[^a-zA-Z0-9]", "", s).lower()
        if strip("".join(all_added_lines)) == strip("".join(all_removed_lines)):
            return None

    diff_text = "\n".join(diff_parts)
    if len(diff_text) > max_diff_size:
        diff_text = diff_text[:max_diff_size] + "\n\n[... truncated ...]"

    return CommitDiff(
        repo_name="",
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
              since_days: int = 30, base_dir: str = "/data/repos",
              clone_depth: int = 6000) -> tuple[list[CommitDiff], str]:
    """
    Full scan pipeline for a single repo.
    Returns (diffs, head_hash).
    """
    log.info(f"=== Scanning {repo_config.name} ===")

    repo = clone_or_pull(repo_config, base_dir, depth=clone_depth)
    head_hash = repo.head.commit.hexsha

    commits = get_new_commits(repo, since_hash=since_hash, since_days=since_days)

    results = []
    skipped = 0

    for i, commit in enumerate(commits):
        if i % 100 == 0 and i > 0:
            log.info(f"Progress: {i}/{len(commits)} commits processed, {len(results)} diffs extracted")

        diff = extract_diff(repo, commit)
        if diff:
            diff.repo_name = repo_config.name
            results.append(diff)
        else:
            skipped += 1

    log.info(f"Extracted {len(results)} meaningful diffs, skipped {skipped}")
    return results, head_hash


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Footnote Scanner")
    parser.add_argument("--config", default="repos.json", help="Repo config file")
    parser.add_argument("--data-dir", default="/data/repos", help="Base dir for cloned repos")
    parser.add_argument("--since-days", type=int, default=30, help="Backfill window in days")
    parser.add_argument("--clone-depth", type=int, default=6000, help="Git clone depth")
    parser.add_argument("--output", default="-", help="Output file (- for stdout)")
    args = parser.parse_args()

    repos = load_repos(args.config)
    all_diffs = []

    for rc in repos:
        diffs, _ = scan_repo(rc, since_days=args.since_days, base_dir=args.data_dir,
                             clone_depth=args.clone_depth)
        all_diffs.extend(diffs)

    output = json.dumps([asdict(d) for d in all_diffs], indent=2, default=str)

    if args.output == "-":
        print(output)
    else:
        with open(args.output, "w") as f:
            f.write(output)
        log.info(f"Wrote {len(all_diffs)} diffs to {args.output}")
