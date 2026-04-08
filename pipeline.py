#!/usr/bin/env python3
"""
Footnote Pipeline — Orchestrates scan → score → store cycle.
"""

import json
import os
import sys
import logging
from dataclasses import asdict
from pathlib import Path

# Add component dirs to path
sys.path.insert(0, str(Path(__file__).parent))

from scanner.scan import load_repos, scan_repo, get_head_sha
from scorer.score import score_diffs
from api.database import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("footnote.pipeline")


def run_pipeline(
    config_path: str = "repos.json",
    db_path: str = "/data/db/footnote.db",
    backfill_days: int = 30,
    github_token: str = None,
    local_url: str = None,
    local_model: str = "gemma4:26b",
    cloud_url: str = None,
    cloud_model: str = "kimi-k2.5:cloud",
    cloud_key: str = None,
    prefilter_threshold: int = 3,
):
    db = Database(db_path)

    try:
        repos = load_repos(config_path)
        log.info(f"Loaded {len(repos)} enabled repos")

        for repo_config in repos:
            log.info(f"\n{'='*60}")
            log.info(f"Processing: {repo_config.name}")
            log.info(f"{'='*60}")

            # Check last scan
            last_hash = db.get_last_scan_hash(repo_config.name)
            if last_hash:
                log.info(f"Last scan hash: {last_hash[:12]}")
            else:
                log.info(f"First scan — backfilling {backfill_days} days")

            # Scan via GitHub API (no git clone needed!)
            diffs = scan_repo(
                repo_config,
                since_hash=last_hash,
                since_days=backfill_days,
                token=github_token,
            )

            if not diffs:
                log.info("No new meaningful diffs found")
                # Still record the scan with current HEAD
                head = get_head_sha(repo_config, token=github_token)
                if head:
                    db.create_scan(repo=repo_config.name, commit_hash=head,
                                   commits_found=0, commits_scored=0)
                continue

            # Score
            diff_dicts = [asdict(d) for d in diffs]
            scored = score_diffs(
                diff_dicts,
                prefilter_threshold=prefilter_threshold,
                local_url=local_url,
                local_model=local_model,
                cloud_url=cloud_url,
                cloud_model=cloud_model,
                cloud_key=cloud_key,
            )

            # Get current HEAD hash
            head = get_head_sha(repo_config, token=github_token)
            if not head:
                head = diffs[0].commit_hash  # Use latest diff commit as fallback

            # Store
            scan_id = db.create_scan(
                repo=repo_config.name,
                commit_hash=head,
                commits_found=len(diffs),
                commits_scored=len(scored),
            )

            stored = 0
            for change in scored:
                change_dict = asdict(change)
                if db.insert_change(scan_id, change_dict):
                    stored += 1

            log.info(f"Stored {stored} new changes (scan #{scan_id})")

        # Print summary
        stats = db.get_stats()
        log.info(f"\n{'='*60}")
        log.info(f"Pipeline complete — {stats['total_changes']} total changes in DB")
        log.info(f"Average score: {stats['avg_score']}")
        log.info(f"By risk: {stats['by_risk_level']}")

    finally:
        db.close()


if __name__ == "__main__":
    run_pipeline(
        config_path=os.environ.get("CONFIG_PATH", "repos.json"),
        db_path=os.environ.get("DB_PATH", "/data/db/footnote.db"),
        backfill_days=int(os.environ.get("BACKFILL_DAYS", "30")),
        github_token=os.environ.get("GITHUB_TOKEN"),
        local_url=os.environ.get("GEMMA_URL"),
        local_model=os.environ.get("LOCAL_MODEL", "gemma4:26b"),
        cloud_url=os.environ.get("CLOUD_BASE_URL"),
        cloud_model=os.environ.get("CLOUD_MODEL", "kimi-k2.5:cloud"),
        cloud_key=os.environ.get("CLOUD_API_KEY"),
        prefilter_threshold=int(os.environ.get("PREFILTER_THRESHOLD", "3")),
    )
