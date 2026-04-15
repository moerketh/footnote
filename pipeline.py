#!/usr/bin/env python3
"""
Footnote Pipeline — Orchestrates scan → score → store cycle.

Resumable: each scored commit is persisted immediately via the API.
On crash + restart, already-scored commits are skipped (API lookup, no LLM call).
"""

import os
import sys
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, str(Path(__file__).parent))

from scanner.scan import load_repos, scan_repo
from scorer.score import (
    get_client, prefilter_score, full_score,
    RateLimitError, APIStatusError,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("footnote.pipeline")

_shutdown = threading.Event()


class ApiClient:
    """HTTP client for the Footnote API ingest endpoints."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        # Retry with backoff for transient network errors
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[502, 503, 504])
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def get_last_scan_hash(self, repo: str) -> str | None:
        r = self.session.get(f"{self.base_url}/ingest/last_scan", params={"repo": repo})
        r.raise_for_status()
        return r.json()["commit_hash"]

    def has_change(self, commit_hash: str) -> bool:
        r = self.session.get(f"{self.base_url}/ingest/has_change", params={"commit_hash": commit_hash})
        r.raise_for_status()
        return r.json()["exists"]

    def create_scan(self, repo: str, commit_hash: str,
                    commits_found: int = 0, commits_scored: int = 0) -> int:
        r = self.session.post(f"{self.base_url}/ingest/scan", params={
            "repo": repo, "commit_hash": commit_hash,
            "commits_found": commits_found, "commits_scored": commits_scored,
        })
        r.raise_for_status()
        return r.json()["scan_id"]

    def insert_change(self, scan_id: int, change: dict) -> int | None:
        r = self.session.post(f"{self.base_url}/ingest/change", params={"scan_id": scan_id}, json=change)
        r.raise_for_status()
        return r.json()["change_id"]

    def update_scan(self, scan_id: int, commits_found: int, commits_scored: int):
        r = self.session.patch(f"{self.base_url}/ingest/scan/{scan_id}", params={
            "commits_found": commits_found, "commits_scored": commits_scored,
        })
        r.raise_for_status()

    def get_stats(self) -> dict:
        r = self.session.get(f"{self.base_url}/stats")
        r.raise_for_status()
        return r.json()


def run_pipeline(
    config_path: str = "repos.json",
    data_dir: str = "/data/repos",
    api_url: str = "http://localhost:8000",
    ingest_token: str = "",
    backfill_days: int = 30,
    clone_depth: int = 6000,
    local_url: str = None,
    local_model: str = "gemma4:26b",
    cloud_url: str = None,
    cloud_model: str = "kimi-k2.5",
    cloud_key: str = None,
    prefilter_threshold: int = 3,
    min_store_score: float = 0,
    max_workers: int = 5,
):
    api = ApiClient(api_url, ingest_token)

    # Set up LLM clients once
    use_prefilter = bool(local_url)
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
            last_hash = api.get_last_scan_hash(repo_config.name)
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
                api.create_scan(repo=repo_config.name, commit_hash=head_hash,
                               commits_found=0, commits_scored=0)
                continue

            # Create scan record upfront (so we have a scan_id for storing changes)
            scan_id = api.create_scan(
                repo=repo_config.name,
                commit_hash=head_hash,
                commits_found=len(diffs),
                commits_scored=0,
            )

            # --- Pass 1: Filter (sequential, fast) ---
            diff_dicts = [asdict(d) for d in diffs]
            stored = 0
            skipped_existing = 0
            skipped_low = 0
            prefiltered = 0
            failed = 0
            rate_limited = False

            to_score = []
            for diff_data in diff_dicts:
                if _shutdown.is_set():
                    break
                if api.has_change(diff_data["commit_hash"]):
                    skipped_existing += 1
                    continue
                if use_prefilter:
                    pre_score = prefilter_score(local_client, local_model, diff_data)
                    if pre_score < prefilter_threshold:
                        prefiltered += 1
                        continue
                to_score.append(diff_data)

            if not _shutdown.is_set():
                log.info(f"Filtered {len(diff_dicts)} diffs: {skipped_existing} already-scored, {prefiltered} pre-filtered, {len(to_score)} to score")
            if to_score and not _shutdown.is_set():
                log.info(f"Scoring {len(to_score)} diffs with {max_workers} workers")

            # --- Pass 2: Cloud score (parallel) ---
            executor = ThreadPoolExecutor(max_workers=max_workers)
            future_to_diff = {}
            try:
                for diff_data in to_score:
                    if _shutdown.is_set() or rate_limited:
                        break
                    fut = executor.submit(full_score, cloud_client, cloud_model, diff_data)
                    future_to_diff[fut] = diff_data

                for fut in as_completed(future_to_diff):
                    if _shutdown.is_set():
                        break
                    diff_data = future_to_diff[fut]
                    try:
                        result = fut.result()
                    except (RateLimitError, APIStatusError) as e:
                        log.warning(f"API error after scoring {stored} commits: {e}")
                        rate_limited = True
                        break
                    except Exception as e:
                        log.error(f"Unexpected error for {diff_data['commit_hash'][:8]}: {e}")
                        failed += 1
                        continue

                    if result is None:
                        failed += 1
                        continue

                    if result.score < min_store_score:
                        skipped_low += 1
                        continue

                    change_dict = asdict(result)
                    if api.insert_change(scan_id, change_dict):
                        stored += 1
                        if stored % 10 == 0:
                            log.info(f"Progress: {stored} scored, {stored + failed + skipped_low}/{len(to_score)} processed")
            except KeyboardInterrupt:
                _shutdown.set()
                log.info("\nShutdown requested — cancelling pending work…")
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

            if rate_limited:
                remaining = len(to_score) - stored - failed - skipped_low
                log.info(f"{remaining} commits remaining. Re-run to continue.")

            # Update scan with final counts
            api.update_scan(scan_id, commits_found=len(diffs),
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

            if _shutdown.is_set():
                break

        # Print summary
        if not _shutdown.is_set():
            stats = api.get_stats()
            log.info(f"\n{'='*60}")
            log.info(f"Pipeline complete — {stats['total_changes']} total changes in DB")
            log.info(f"Average score: {stats['avg_score']}")
            log.info(f"By risk: {stats['by_risk_level']}")

    except KeyboardInterrupt:
        _shutdown.set()
        log.info("\nShutdown requested.")


if __name__ == "__main__":
    run_pipeline(
        config_path=os.environ.get("CONFIG_PATH", "repos.json"),
        data_dir=os.environ.get("DATA_DIR", "/data/repos"),
        api_url=os.environ.get("API_URL", "http://localhost:8000"),
        ingest_token=os.environ.get("INGEST_TOKEN", ""),
        backfill_days=int(os.environ.get("BACKFILL_DAYS", "30")),
        clone_depth=int(os.environ.get("CLONE_DEPTH", "6000")),
        local_url=os.environ.get("LOCAL_OLLAMA_URL"),
        local_model=os.environ.get("LOCAL_MODEL", "gemma4:26b"),
        cloud_url=os.environ.get("CLOUD_OLLAMA_URL"),
        cloud_model=os.environ.get("CLOUD_MODEL", "kimi-k2.5"),
        cloud_key=os.environ.get("CLOUD_API_KEY"),
        prefilter_threshold=int(os.environ.get("PREFILTER_THRESHOLD", "3")),
        min_store_score=float(os.environ.get("MIN_STORE_SCORE", "0")),
        max_workers=int(os.environ.get("SCORING_WORKERS", "5")),
    )
