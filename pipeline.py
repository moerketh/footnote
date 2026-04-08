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

# Add parent dirs to path
sys.path.insert(0, str(Path(__file__).parent / "scanner"))
sys.path.insert(0, str(Path(__file__).parent / "scorer"))
sys.path.insert(0, str(Path(__file__).parent / "api"))

from scanner.scan import load_repos, scan_repo
from scorer.score import score_diffs
from api.database import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("footnote.pipeline")


def run_pipeline(
    config_path: str = "repos.json",
    data_dir: str = "/data/repos",
    db_path: str = "/data/db/footnote.db",
    backfill_days: int = 30,
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

            # Scan
            diffs = scan_repo(
                repo_config,
                since_hash=last_hash,
                since_days=backfill_days,
                base_dir=data_dir,
            )

            if not diffs:
                log.info("No new meaningful diffs found")
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
            from git import Repo
            repo_path = Path(data_dir) / repo_config.name
            head_hash = Repo(repo_path).head.commit.hexsha

            # Store
            scan_id = db.create_scan(
                repo=repo_config.name,
                commit_hash=head_hash,
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
        data_dir=os.environ.get("DATA_DIR", "/data/repos"),
        db_path=os.environ.get("DB_PATH", "/data/db/footnote.db"),
        backfill_days=int(os.environ.get("BACKFILL_DAYS", "30")),
        local_url=os.environ.get("GEMMA_URL"),
        local_model=os.environ.get("LOCAL_MODEL", "gemma4:26b"),
        cloud_url=os.environ.get("CLOUD_BASE_URL"),
        cloud_model=os.environ.get("CLOUD_MODEL", "kimi-k2.5:cloud"),
        cloud_key=os.environ.get("CLOUD_API_KEY"),
        prefilter_threshold=int(os.environ.get("PREFILTER_THRESHOLD", "3")),
    )
