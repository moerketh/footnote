"""Insert dummy data for GUI testing."""
import json
import sqlite3
import os
from pathlib import Path
from datetime import datetime, timedelta
import random

DB_PATH = os.environ.get("DB_PATH", "/data/db/footnote.db")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

REPOS = ["azure-docs", "aws-docs", "gcp-docs"]
AUTHORS = ["alice@example.com", "bob@example.com", "carol@example.com"]
RISK_LEVELS = ["high", "medium", "low", "informational"]
TAGS_POOL = ["authentication", "authorization", "encryption", "network", "iam",
             "secrets", "tls", "firewall", "rbac", "mfa", "logging", "compliance"]

CHANGES = [
    {
        "repo_name": "azure-docs",
        "commit_hash": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        "commit_message": "Update MFA requirement for privileged accounts\n\nDocument that all Global Admins must enable MFA.",
        "author": "alice@example.com",
        "score": 9.0,
        "risk_level": "critical",
        "summary": "Documentation update clarifying MFA is now mandatory for all Global Administrator accounts in Azure AD. Failure to comply may result in account lockout.",
        "rationale": "Mandatory MFA enforcement for all Azure portal users changes authentication defaults platform-wide, with potential lockout risk.",
        "scoring_details": {"cia": {"confidentiality": True, "integrity": True, "availability": True}, "change_nature": "behavior_change", "actionability": "required", "broad_scope": True},
        "files_changed": ["articles/active-directory/fundamentals/mfa-required.md"],
        "tags": ["auth-change", "identity"],
        "services": ["Azure Active Directory", "Microsoft Entra ID"],
        "diff_summary": "-MFA is recommended for privileged accounts.\n+MFA is required for all Global Administrator accounts effective immediately.",
        "days_ago": 1,
    },
    {
        "repo_name": "azure-docs",
        "commit_hash": "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3",
        "commit_message": "Deprecate TLS 1.0 and 1.1 in Azure Storage",
        "author": "bob@example.com",
        "score": 10.0,
        "risk_level": "critical",
        "summary": "Azure Storage will drop support for TLS 1.0 and 1.1. Clients must migrate to TLS 1.2+ by the stated deadline or connections will be rejected.",
        "rationale": "Deprecation of TLS 1.0/1.1 is a breaking encryption change requiring client migration before deadline.",
        "scoring_details": {"cia": {"confidentiality": True, "integrity": True, "availability": True}, "change_nature": "critical", "actionability": "required", "broad_scope": True},
        "files_changed": ["articles/storage/common/transport-layer-security-configure-minimum-version.md"],
        "tags": ["encryption", "deprecation"],
        "services": ["Azure Blob Storage", "Azure Files"],
        "diff_summary": "-TLS 1.0, 1.1, and 1.2 are supported.\n+Only TLS 1.2 and above are supported as of November 2024.",
        "days_ago": 3,
    },
    {
        "repo_name": "aws-docs",
        "commit_hash": "c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
        "commit_message": "IAM: remove wildcard resource from example policies",
        "author": "carol@example.com",
        "score": 7.0,
        "risk_level": "high",
        "summary": "Example IAM policies updated to replace Resource: '*' with specific ARNs, reflecting least-privilege best practices.",
        "rationale": "Default change from wildcard to scoped resources platform-wide, requiring action from deployments copying example policies.",
        "scoring_details": {"cia": {"confidentiality": True, "integrity": False, "availability": False}, "change_nature": "behavior_change", "actionability": "required", "broad_scope": True},
        "files_changed": ["docs/iam/access_policies_examples.md", "docs/iam/best-practices.md"],
        "tags": ["permission-change", "default-behavior"],
        "services": ["AWS IAM", "Amazon S3"],
        "diff_summary": '-  "Resource": "*"\n+  "Resource": "arn:aws:s3:::my-bucket/*"',
        "days_ago": 5,
    },
    {
        "repo_name": "gcp-docs",
        "commit_hash": "d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5",
        "commit_message": "Update VPC firewall rule defaults documentation",
        "author": "alice@example.com",
        "score": 6.0,
        "risk_level": "medium",
        "summary": "Documentation clarifies that default VPC firewall rules now block all ingress traffic unless explicitly permitted.",
        "rationale": "Default firewall behavior changed to deny-all ingress, requiring explicit allow rules for any inbound traffic.",
        "scoring_details": {"cia": {"confidentiality": True, "integrity": False, "availability": False}, "change_nature": "behavior_change", "actionability": "recommended", "broad_scope": True},
        "files_changed": ["docs/vpc/firewalls.md"],
        "tags": ["network-change", "default-behavior"],
        "services": ["Google VPC", "Cloud Firewall"],
        "diff_summary": "-Ingress traffic is allowed by default.\n+All ingress traffic is blocked by default; add explicit allow rules as needed.",
        "days_ago": 7,
    },
    {
        "repo_name": "aws-docs",
        "commit_hash": "e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6",
        "commit_message": "Add CloudTrail logging requirements for S3 data events",
        "author": "bob@example.com",
        "score": 5.0,
        "risk_level": "medium",
        "summary": "New guidance recommends enabling CloudTrail data event logging for S3 buckets containing sensitive data.",
        "rationale": "New monitoring feature for S3 data event logging recommended for compliance with sensitive data regulations.",
        "scoring_details": {"cia": {"confidentiality": True, "integrity": False, "availability": False}, "change_nature": "new_feature", "actionability": "recommended", "broad_scope": True},
        "files_changed": ["docs/cloudtrail/s3-data-events.md"],
        "tags": ["monitoring", "compliance"],
        "services": ["AWS CloudTrail", "Amazon S3"],
        "diff_summary": "+Enable S3 data event logging in CloudTrail for all buckets containing PII or regulated data.",
        "days_ago": 10,
    },
    {
        "repo_name": "azure-docs",
        "commit_hash": "a2b3c4d5e6f7a2b3c4d5e6f7a2b3c4d5e6f7a2b3",
        "commit_message": "Update Azure Key Vault access policy documentation",
        "author": "alice@example.com",
        "score": 4.0,
        "risk_level": "medium",
        "summary": "Clarifies that Key Vault access policies should be scoped to specific secret/key/certificate operations rather than granting broad permissions.",
        "rationale": "Clarification of existing best practice for Key Vault least-privilege; no behavior change.",
        "scoring_details": {"cia": {"confidentiality": True, "integrity": False, "availability": False}, "change_nature": "clarification", "actionability": "recommended", "broad_scope": True},
        "files_changed": ["articles/key-vault/general/assign-access-policy.md"],
        "tags": ["permission-change"],
        "services": ["Azure Key Vault"],
        "diff_summary": "-Grant the application 'all' permissions to secrets.\n+Grant only the minimum required permissions (e.g., get, list) to secrets.",
        "days_ago": 20,
    },
    {
        "repo_name": "gcp-docs",
        "commit_hash": "f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1",
        "commit_message": "Fix typo in Secret Manager rotation example",
        "author": "carol@example.com",
        "score": 0.0,
        "risk_level": "informational",
        "summary": "Minor typo fix in the Secret Manager automatic rotation code example. No functional change.",
        "rationale": "Typo fix with no security impact.",
        "scoring_details": {"cia": {"confidentiality": False, "integrity": False, "availability": False}, "change_nature": "cosmetic", "actionability": "none", "broad_scope": False},
        "files_changed": ["docs/secret-manager/rotation.md"],
        "tags": [],
        "services": ["Google Secret Manager"],
        "diff_summary": "-roatation_period\n+rotation_period",
        "days_ago": 14,
    },
    {
        "repo_name": "aws-docs",
        "commit_hash": "b3c4d5e6f7a2b3c4d5e6f7a2b3c4d5e6f7a2b3c4",
        "commit_message": "Add note about public S3 bucket deprecation warning",
        "author": "bob@example.com",
        "score": 1.0,
        "risk_level": "informational",
        "summary": "Added an informational note that AWS now displays a warning in the console when a bucket is configured for public access.",
        "rationale": "Informational console warning addition; no behavior or access change.",
        "scoring_details": {"cia": {"confidentiality": False, "integrity": False, "availability": False}, "change_nature": "clarification", "actionability": "none", "broad_scope": False},
        "files_changed": ["docs/s3/access-control/block-public-access.md"],
        "tags": ["compliance"],
        "services": ["Amazon S3"],
        "diff_summary": "+AWS console now shows a warning banner for buckets with public access enabled.",
        "days_ago": 25,
    },
]

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys=ON")
conn.executescript("""
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    commit_hash TEXT NOT NULL,
    scanned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    commits_found INTEGER DEFAULT 0,
    commits_scored INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER REFERENCES scans(id),
    repo_name TEXT NOT NULL,
    commit_hash TEXT NOT NULL UNIQUE,
    commit_date DATETIME,
    commit_message TEXT,
    author TEXT,
    files_changed TEXT,
    diff_summary TEXT,
    diff_full TEXT,
    score REAL DEFAULT 0,
    risk_level TEXT DEFAULT 'informational',
    summary TEXT,
    rationale TEXT DEFAULT '',
    scoring_details TEXT DEFAULT '{}',
    services TEXT,
    stats TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS change_tags (
    change_id INTEGER REFERENCES changes(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (change_id, tag)
);
""")

scan_id = conn.execute(
    "INSERT INTO scans (repo, commit_hash, commits_found, commits_scored) VALUES (?, ?, ?, ?)",
    ("seed", "0000000000000000000000000000000000000000", len(CHANGES), len(CHANGES))
).lastrowid

now = datetime.utcnow()
inserted = 0
for c in CHANGES:
    commit_date = (now - timedelta(days=c["days_ago"])).strftime("%Y-%m-%d %H:%M:%S")
    try:
        cur = conn.execute(
            """INSERT OR REPLACE INTO changes
               (scan_id, repo_name, commit_hash, commit_date, commit_message,
                author, files_changed, diff_summary, diff_full, score,
                risk_level, summary, rationale, scoring_details, services, stats)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                scan_id, c["repo_name"], c["commit_hash"], commit_date,
                c["commit_message"], c["author"],
                json.dumps(c["files_changed"]),
                c["diff_summary"], c["diff_summary"],
                c["score"], c["risk_level"], c["summary"],
                c.get("rationale", ""),
                json.dumps(c.get("scoring_details", {})),
                json.dumps(c.get("services", [])), json.dumps({}),
            )
        )
        change_id = cur.lastrowid
        for tag in c["tags"]:
            conn.execute(
                "INSERT OR IGNORE INTO change_tags (change_id, tag) VALUES (?, ?)",
                (change_id, tag)
            )
        inserted += 1
    except sqlite3.IntegrityError:
        print(f"  skip duplicate: {c['commit_hash'][:8]}")

conn.commit()
conn.close()
print(f"Seeded {inserted} changes.")
