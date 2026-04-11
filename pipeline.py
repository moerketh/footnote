#!/usr/bin/env python3
"""
Footnote Pipeline — Orchestrates scan → score → store cycle.

Resumable: each scored commit is persisted immediately. On crash + restart,
already-scored commits are skipped (DB lookup, no LLM call).
"""

import os
import sys
import logging
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scanner.scan import load_repos, scan_repo
from scorer.score import (
    get_client, prefilter_score, full_score,
    RateLimitError, APIStatusError,
)
from api.database import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("footnote.pipeline")


def run_pipeline(
    config_path: str = "repos.json",
    data_dir: str = "/data/repos",
    db_path: str = "/data/db/footnote.db",
    backfill_days: int = 30,
    clone_depth: int = 6000,
    local_url: str = None,
    local_model: str = "gemma4:26b",
    cloud_url: str = None,
    cloud_model: str = "kimi-k2.5",
    cloud_key: str = None,
    prefilter_threshold: int = 3,
    min_store_score: float = 3.0,
):
    db = Database(db_path)

    # Set up LLM clients once
    use_prefilter = local_url is not None
    if use_prefilter:
        local_client = get_client(local_url, "ollama")

    if not cloud_url:
        log.error("No CLOUD_OLLAMA_URL configured")
        return

    cloud_client = get_client(cloud_url, cloud_key or "")

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

            # Always use time-based scanning (since_days) so increasing
            # BACKFILL_DAYS actually reaches further back. The has_change()
            # check in the scoring loop prevents re-scoring already-processed
            # commits, so re-scanning is cheap (local git only, no LLM calls).
            diffs, head_hash = scan_repo(
                repo_config,
                since_hash=None,
                since_days=backfill_days,
                base_dir=data_dir,
                clone_depth=clone_depth,
            )

            if not diffs:
                log.info("No new meaningful diffs found")
                db.create_scan(repo=repo_config.name, commit_hash=head_hash,
                               commits_found=0, commits_scored=0)
                continue

            # Create scan record upfront (so we have a scan_id for storing changes)
            scan_id = db.create_scan(
                repo=repo_config.name,
                commit_hash=head_hash,
                commits_found=len(diffs),
                commits_scored=0,
            )

            # Score and store one commit at a time (resumable)
            diff_dicts = [asdict(d) for d in diffs]
            stored = 0
            skipped_existing = 0
            skipped_low = 0
            prefiltered = 0
            failed = 0
            rate_limited = False

            for i, diff_data in enumerate(diff_dicts):
                # Skip if already scored (resume-safe)
                if db.has_change(diff_data["commit_hash"]):
                    skipped_existing += 1
                    continue

                # Tier 1: Pre-filter (local, fast)
                if use_prefilter:
                    pre_score = prefilter_score(local_client, local_model, diff_data)
                    if pre_score < prefilter_threshold:
                        prefiltered += 1
                        continue

                # Tier 2: Full score (cloud, may fail)
                try:
                    result = full_score(cloud_client, cloud_model, diff_data)
                except (RateLimitError, APIStatusError) as e:
                    remaining = len(diff_dicts) - i - 1
                    log.warning(f"API error after scoring {stored} commits: {e}")
                    log.info(f"{remaining} commits remaining. Re-run to continue.")
                    rate_limited = True
                    break

                if result is None:
                    failed += 1
                    continue

                if result.score < min_store_score:
                    skipped_low += 1
                    continue

                change_dict = asdict(result)
                if db.insert_change(scan_id, change_dict):
                    stored += 1
                    if stored % 10 == 0:
                        log.info(f"Progress: {stored} scored, {i+1}/{len(diff_dicts)} processed")

            # Update scan with final counts
            db.update_scan(scan_id, commits_found=len(diffs),
                           commits_scored=stored)

            if skipped_existing:
                log.info(f"Skipped {skipped_existing} already-scored commits (resumed)")
            if prefiltered:
                log.info(f"Pre-filtered {prefiltered} low-relevance commits")
            if skipped_low:
                log.info(f"Skipped {skipped_low} below min_store_score={min_store_score}")
            if failed:
                log.info(f"Failed to score {failed} commits")
            log.info(f"Stored {stored} new changes (scan #{scan_id})")

            if rate_limited:
                log.info("Stopping due to API rate limit. Re-run to continue.")
                break

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
        clone_depth=int(os.environ.get("CLONE_DEPTH", "6000")),
        local_url=os.environ.get("LOCAL_OLLAMA_URL"),
        local_model=os.environ.get("LOCAL_MODEL", "gemma4:26b"),
        cloud_url=os.environ.get("CLOUD_OLLAMA_URL"),
        cloud_model=os.environ.get("CLOUD_MODEL", "kimi-k2.5"),
        cloud_key=os.environ.get("CLOUD_API_KEY"),
        prefilter_threshold=int(os.environ.get("PREFILTER_THRESHOLD", "3")),
        min_store_score=float(os.environ.get("MIN_STORE_SCORE", "3.0")),
    )
