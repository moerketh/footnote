"""
Scanner unit tests — noise filters, file filters, diff extraction, and edge cases.

Run: python -m pytest scanner/tests/test_scanner.py -v
"""

import re
import pytest
from unittest.mock import MagicMock, PropertyMock
from scanner.scan import (
    is_noise_commit,
    is_noise_file,
    extract_diff,
    load_repos,
    NOISE_COMMIT_PATTERNS,
    SKIP_PATTERNS,
    LOCALE_PATTERNS,
)


# ---------------------------------------------------------------------------
# Helpers to build mock git objects
# ---------------------------------------------------------------------------

def make_commit(message, files=None, hexsha="abc1234def5678"):
    """Create a mock commit with a parent and diffable files."""
    commit = MagicMock()
    commit.message = message
    commit.hexsha = hexsha
    commit.committed_date = 1700000000
    commit.author = "Test Author"

    parent = MagicMock()
    commit.parents = [parent]

    if files is not None:
        mock_diffs = []
        for filepath, patch_text in files.items():
            d = MagicMock()
            d.a_path = filepath
            d.b_path = filepath
            d.diff = patch_text.encode("utf-8")
            mock_diffs.append(d)
        parent.diff.return_value = mock_diffs
    else:
        parent.diff.return_value = []

    return commit


# ===========================================================================
# NOISE COMMIT PATTERNS
# ===========================================================================


class TestNoiseCommitPatterns:
    """Tests for commit message noise filtering."""

    # --- Standard merge commits (should be filtered) ---

    def test_merge_pull_request_is_noise(self):
        c = make_commit("Merge pull request #1234 from user/feature-branch")
        assert is_noise_commit(c) is True

    def test_merge_branch_is_noise(self):
        c = make_commit("Merge branch 'main' into feature")
        assert is_noise_commit(c) is True

    # --- Squash merges (should NOT be filtered) ---

    def test_squash_merge_with_pr_title_passes(self):
        c = make_commit("Add MFA enforcement documentation (#1234)")
        assert is_noise_commit(c) is False

    def test_squash_merge_descriptive_title_passes(self):
        c = make_commit("Update default security settings for storage accounts")
        assert is_noise_commit(c) is False

    # --- Typo/grammar fixes (should be filtered) ---

    def test_fix_typo_is_noise(self):
        c = make_commit("Fix typo in overview.md")
        assert is_noise_commit(c) is True

    def test_fixed_spelling_is_noise(self):
        c = make_commit("Fixed spelling in security article")
        assert is_noise_commit(c) is True

    def test_fix_grammar_is_noise(self):
        c = make_commit("fix grammar in rbac docs")
        assert is_noise_commit(c) is True

    def test_fix_formatting_is_noise(self):
        c = make_commit("Fix formatting in table")
        assert is_noise_commit(c) is True

    def test_fix_broken_link_is_noise(self):
        c = make_commit("Fixed broken link to Azure portal")
        assert is_noise_commit(c) is True

    def test_fix_whitespace_is_noise(self):
        c = make_commit("fix whitespace issues")
        assert is_noise_commit(c) is True

    # --- Fix messages that are NOT typos (should pass through) ---

    def test_fix_security_bug_passes(self):
        c = make_commit("Fix incorrect permission requirement for API")
        assert is_noise_commit(c) is False

    def test_fix_configuration_passes(self):
        c = make_commit("Fix default TLS version in documentation")
        assert is_noise_commit(c) is False

    def test_fix_api_endpoint_passes(self):
        c = make_commit("Fix API endpoint authentication requirement")
        assert is_noise_commit(c) is False

    # --- Locale commits (should be filtered) ---

    def test_locale_batch_is_noise(self):
        c = make_commit("locale update for ja-jp")
        assert is_noise_commit(c) is True

    def test_locale_prefix_is_noise(self):
        c = make_commit("Locale sync from main")
        assert is_noise_commit(c) is True

    # --- Revert patterns ---

    def test_double_revert_is_noise(self):
        """Revert of a revert is noise (restores original state)."""
        c = make_commit('Revert "Revert "Add MFA docs""')
        assert is_noise_commit(c) is True

    def test_single_revert_passes(self):
        """A single revert could rollback a security change — must be scored."""
        c = make_commit('Revert "Add mandatory MFA enforcement"')
        assert is_noise_commit(c) is False

    # --- Normal security-relevant commits (should all pass) ---

    def test_security_default_change_passes(self):
        c = make_commit("Change default blob access to private")
        assert is_noise_commit(c) is False

    def test_deprecation_notice_passes(self):
        c = make_commit("Add deprecation notice for classic admin roles")
        assert is_noise_commit(c) is False

    def test_breaking_change_passes(self):
        c = make_commit("Breaking: app-only tokens require admin consent")
        assert is_noise_commit(c) is False

    def test_permission_update_passes(self):
        c = make_commit("Update required permissions for Key Vault access")
        assert is_noise_commit(c) is False


# ===========================================================================
# FILE PATH FILTERS
# ===========================================================================


class TestFilePathFilters:
    """Tests for file path noise filtering."""

    # --- Binary files (should be filtered) ---

    def test_png_is_noise(self):
        assert is_noise_file("articles/media/diagram.png") is True

    def test_jpg_is_noise(self):
        assert is_noise_file("articles/media/screenshot.JPG") is True

    def test_svg_is_noise(self):
        assert is_noise_file("articles/media/architecture.svg") is True

    def test_pdf_is_noise(self):
        assert is_noise_file("downloads/whitepaper.pdf") is True

    def test_zip_is_noise(self):
        assert is_noise_file("samples/code.zip") is True

    # --- Publishing metadata (should be filtered) ---

    def test_breadcrumb_toc_is_noise(self):
        assert is_noise_file("articles/security/bread-toc.yml") is True

    def test_zone_pivot_is_noise(self):
        assert is_noise_file("articles/zone-pivot-groups.yml") is True

    def test_openpublishing_is_noise(self):
        assert is_noise_file(".openpublishing.redirection.json") is True

    # --- Locale directories (should be filtered) ---

    def test_japanese_locale_is_noise(self):
        assert is_noise_file("articles/ja-jp/security/overview.md") is True

    def test_german_locale_is_noise(self):
        assert is_noise_file("articles/de-de/identity/mfa.md") is True

    def test_chinese_locale_is_noise(self):
        assert is_noise_file("articles/zh-cn/storage/security.md") is True

    def test_portuguese_brazil_locale_is_noise(self):
        assert is_noise_file("articles/pt-br/security/defaults.md") is True

    # --- Valid documentation files (should pass) ---

    def test_english_markdown_passes(self):
        assert is_noise_file("articles/security/overview.md") is False

    def test_yaml_config_passes(self):
        assert is_noise_file("articles/security/toc.yml") is False

    def test_nested_security_doc_passes(self):
        assert is_noise_file("articles/identity/conditional-access/policy-defaults.md") is False

    def test_root_doc_passes(self):
        assert is_noise_file("README.md") is False


# ===========================================================================
# DIFF EXTRACTION — PUNCTUATION / CAPITALIZATION FILTER
# ===========================================================================


class TestPunctuationFilter:
    """Tests for the small-diff punctuation/capitalization filter."""

    def test_period_only_change_is_filtered(self):
        """Adding a period to end of sentence — pure punctuation."""
        c = make_commit("Minor edit", files={
            "articles/security/overview.md": (
                "-Use the Azure portal to configure settings\n"
                "+Use the Azure portal to configure settings.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_comma_change_is_filtered(self):
        """Swapping punctuation — pure formatting."""
        c = make_commit("Fix punctuation", files={
            "articles/overview.md": (
                "-For more information, see [link](url)\n"
                "+For more information; see [link](url)\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_capitalization_only_is_filtered(self):
        """Changing capitalization — no semantic change."""
        c = make_commit("Fix casing", files={
            "articles/overview.md": (
                "-use the Azure Portal\n"
                "+Use the Azure portal\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_markdown_formatting_change_is_filtered(self):
        """Changing markdown bold/italic markers — pure formatting."""
        c = make_commit("Format fix", files={
            "articles/overview.md": (
                "-Use *the* Azure portal\n"
                "+Use **the** Azure portal\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_real_word_change_passes(self):
        """Changing actual content must pass through."""
        c = make_commit("Update policy", files={
            "articles/security/mfa.md": (
                "-MFA is optional for all users\n"
                "+MFA is required for all users\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None

    def test_new_line_added_passes(self):
        """A new line with no corresponding removal — real content."""
        c = make_commit("Add security note", files={
            "articles/security/overview.md": (
                "+> [!IMPORTANT] This API now requires admin consent.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None

    def test_line_removed_passes(self):
        """A removed line with no replacement — real content."""
        c = make_commit("Remove note", files={
            "articles/security/overview.md": (
                "-This feature is available in preview.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None

    def test_large_diff_skips_punctuation_check(self):
        """Diffs with >4 changed lines bypass the punctuation filter entirely."""
        lines = "".join(
            f"-line {i} old\n+line {i} new.\n" for i in range(5)
        )
        c = make_commit("Many formatting fixes", files={
            "articles/overview.md": lines
        })
        result = extract_diff(MagicMock(), c)
        # Should pass through even if it's all punctuation — >4 lines
        assert result is not None

    def test_empty_to_content_passes(self):
        """Adding content where there was none before."""
        c = make_commit("Add security warning", files={
            "articles/security/defaults.md": (
                "+All new storage accounts default to private access.\n"
                "+You must explicitly enable public blob access.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None

    def test_hyperlink_added_to_existing_text_is_filtered(self):
        """Wrapping existing text in a markdown link — pure formatting."""
        c = make_commit("Add link to Azure endpoint docs", files={
            "articles/app-service/configure-ssl-certificate.md": (
                "-If using Azure Traffic Manager, the site must be configured as an Azure Endpoint.\n"
                "+If using Azure Traffic Manager, the site must be configured as an [Azure endpoint](/azure/traffic-manager/traffic-manager-endpoint-types#azure-endpoints).\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_hyperlink_removed_is_filtered(self):
        """Removing a link but keeping the text — pure formatting."""
        c = make_commit("Remove broken link", files={
            "articles/overview.md": (
                "-See the [Azure portal](https://portal.azure.com) for details.\n"
                "+See the Azure portal for details.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_hyperlink_url_changed_is_filtered(self):
        """Changing the URL but keeping the link text — no content change."""
        c = make_commit("Fix link URL", files={
            "articles/overview.md": (
                "-See [the docs](https://old-url.com/page).\n"
                "+See [the docs](https://new-url.com/page).\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_hyperlink_with_text_change_passes(self):
        """Link added AND the visible text changed — must be scored."""
        c = make_commit("Update endpoint type", files={
            "articles/overview.md": (
                "-the site must be configured as a standard endpoint.\n"
                "+the site must be configured as a [premium endpoint](/azure/premium).\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None


# ===========================================================================
# DIFF EXTRACTION — PURE MOVE FILTER
# ===========================================================================


class TestPureMoveFilter:
    """Tests for detecting content moved without changes."""

    def test_note_moved_up_is_filtered(self):
        """Real-world case: important note moved closer to referenced table."""
        c = make_commit("Moved 'important' note up closer to the table", files={
            "articles/app-service/configure-ssl-certificate.md": (
                "+> [!IMPORTANT]\n"
                "+> The values in the table are application (client) IDs.\n"
                "-> [!IMPORTANT]\n"
                "-> The values in the table are application (client) IDs.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_section_reordered_is_filtered(self):
        """Multiple lines moved to a different position."""
        c = make_commit("Reorder sections", files={
            "articles/security/overview.md": (
                "-## Prerequisites\n"
                "-You need Contributor role.\n"
                "-You need an Azure subscription.\n"
                "+## Prerequisites\n"
                "+You need Contributor role.\n"
                "+You need an Azure subscription.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_move_across_files_is_filtered(self):
        """Content moved from one file to another."""
        c = make_commit("Move security note to correct file", files={
            "articles/security/old-page.md": (
                "-MFA is required for all admin accounts.\n"
            ),
            "articles/security/new-page.md": (
                "+MFA is required for all admin accounts.\n"
            ),
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_move_with_edit_passes(self):
        """Content moved AND modified — must be scored."""
        c = make_commit("Move and update note", files={
            "articles/security/overview.md": (
                "-MFA is optional for admin accounts.\n"
                "+MFA is required for all admin accounts.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None

    def test_move_with_punctuation_fix_is_filtered(self):
        """Content moved and a period added — still just a move."""
        c = make_commit("Move note, fix punctuation", files={
            "articles/security/overview.md": (
                "+You need Contributor role.\n"
                "-You need Contributor role\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_move_with_capitalization_fix_is_filtered(self):
        """Content moved and capitalization changed — still just a move."""
        c = make_commit("Move and fix casing", files={
            "articles/security/overview.md": (
                "-see the Azure Portal for details\n"
                "+See the Azure portal for details\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_move_with_whitespace_change_is_filtered(self):
        """Content moved with extra spaces — still just a move."""
        c = make_commit("Move and reformat", files={
            "articles/security/overview.md": (
                "-You  need   Contributor role\n"
                "+You need Contributor role\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_move_with_markdown_reformatting_is_filtered(self):
        """Content moved with bold/italic changes — still just a move."""
        c = make_commit("Move note and reformat", files={
            "articles/security/overview.md": (
                "-Use *the* Azure **portal** to configure.\n"
                "+Use **the** Azure *portal* to configure.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_move_with_extra_line_added_passes(self):
        """Content moved plus a new line added — not a pure move."""
        c = make_commit("Move note and add warning", files={
            "articles/security/overview.md": (
                "-## Prerequisites\n"
                "-You need Contributor role.\n"
                "+## Prerequisites\n"
                "+You need Contributor role.\n"
                "+> [!WARNING] This role grants write access.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None

    def test_move_with_line_removed_passes(self):
        """Content moved but one line dropped — not a pure move."""
        c = make_commit("Move and trim section", files={
            "articles/security/overview.md": (
                "-## Prerequisites\n"
                "-You need Contributor role.\n"
                "-See also: legacy docs.\n"
                "+## Prerequisites\n"
                "+You need Contributor role.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None

    def test_pure_addition_not_affected(self):
        """Pure additions (no removals) must not be caught by move filter."""
        c = make_commit("Add new section", files={
            "articles/security/overview.md": (
                "+## New Security Requirements\n"
                "+All accounts must enable MFA by March 2025.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None

    def test_pure_deletion_not_affected(self):
        """Pure deletions (no additions) must not be caught by move filter."""
        c = make_commit("Remove deprecated section", files={
            "articles/security/overview.md": (
                "-## Legacy Authentication\n"
                "-Basic auth is still supported.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None


# ===========================================================================
# DIFF EXTRACTION — FILE TYPE FILTERING
# ===========================================================================


class TestFileTypeFiltering:
    """Tests for file extension filtering in extract_diff."""

    def test_python_file_is_ignored(self):
        """Only .md/.yml/.yaml files should be processed."""
        c = make_commit("Update script", files={
            "scripts/deploy.py": "+import os\n"
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_json_file_is_ignored(self):
        c = make_commit("Update config", files={
            "config/settings.json": '+  "key": "value"\n'
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_markdown_is_accepted(self):
        c = make_commit("Security update", files={
            "articles/security/rbac.md": (
                "-Users need Reader role\n"
                "+Users need Contributor role\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None

    def test_yml_is_accepted(self):
        c = make_commit("Update config", files={
            "articles/toc.yml": (
                "-  name: Old Section\n"
                "+  name: Security Section\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None

    def test_yaml_is_accepted(self):
        c = make_commit("Update config", files={
            "config/roles.yaml": (
                "-  role: Reader\n"
                "+  role: Contributor\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None

    def test_mix_of_relevant_and_irrelevant_files(self):
        """Commit with both .md and .png — only .md should be in result."""
        c = make_commit("Update docs with screenshot", files={
            "articles/security/overview.md": (
                "-Old security guidance\n"
                "+New security guidance with stricter defaults\n"
            ),
            "articles/media/screenshot.png": "+binary data\n",
        })
        # The .png passes is_noise_file, but also fails the .md/.yml extension check
        result = extract_diff(MagicMock(), c)
        assert result is not None
        assert "articles/security/overview.md" in result.files_changed
        assert len([f for f in result.files_changed if f.endswith(".png")]) == 0


# ===========================================================================
# DIFF EXTRACTION — EDGE CASES
# ===========================================================================


class TestExtractDiffEdgeCases:
    """Edge cases for extract_diff."""

    def test_no_parents_returns_none(self):
        """Initial commit (no parents) should be skipped."""
        c = make_commit("Initial commit", files={
            "README.md": "+# Hello\n"
        })
        c.parents = []
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_noise_commit_returns_none(self):
        """Commit matching noise pattern should be skipped."""
        c = make_commit("Merge pull request #99 from user/branch", files={
            "articles/security/overview.md": (
                "-old content\n"
                "+new content\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_all_files_are_noise(self):
        """If all files match noise patterns, result should be None."""
        c = make_commit("Update images", files={
            "articles/media/icon.png": "+binary\n",
            "articles/media/logo.svg": "+<svg>\n",
        })
        result = extract_diff(MagicMock(), c)
        assert result is None

    def test_diff_stats_are_correct(self):
        """Stats should count additions and deletions correctly."""
        c = make_commit("Security update", files={
            "articles/security/defaults.md": (
                "-Public access is enabled by default.\n"
                "-Users can configure access settings.\n"
                "+Public access is now disabled by default.\n"
                "+Admins must explicitly enable public access.\n"
                "+A new audit log entry is created for access changes.\n"
            )
        })
        result = extract_diff(MagicMock(), c)
        assert result is not None
        assert result.stats["additions"] == 3
        assert result.stats["deletions"] == 2
        assert result.stats["files"] == 1

    def test_diff_truncation(self):
        """Large diffs should be truncated with a message."""
        big_patch = "\n".join(
            f"+{'x' * 100} line {i}" for i in range(1000)
        )
        c = make_commit("Huge update", files={
            "articles/security/overview.md": big_patch
        })
        result = extract_diff(MagicMock(), c, max_diff_size=500)
        assert result is not None
        assert "[... truncated ...]" in result.diff_text
        assert len(result.diff_text) < 600


# ===========================================================================
# REPO CONFIG LOADING
# ===========================================================================


class TestLoadRepos:
    """Tests for repos.json loading."""

    def test_load_only_enabled_repos(self, tmp_path):
        config = tmp_path / "repos.json"
        config.write_text('{"repos": ['
            '{"url": "https://github.com/a/b", "branch": "main", "name": "enabled-repo", "enabled": true},'
            '{"url": "https://github.com/c/d", "branch": "main", "name": "disabled-repo", "enabled": false}'
            ']}')
        repos = load_repos(str(config))
        assert len(repos) == 1
        assert repos[0].name == "enabled-repo"

    def test_description_field_is_loaded(self, tmp_path):
        config = tmp_path / "repos.json"
        config.write_text('{"repos": ['
            '{"url": "https://github.com/a/b", "branch": "main", "name": "test",'
            ' "description": "Watch for security changes"}'
            ']}')
        repos = load_repos(str(config))
        assert repos[0].description == "Watch for security changes"

    def test_missing_description_defaults_empty(self, tmp_path):
        config = tmp_path / "repos.json"
        config.write_text('{"repos": ['
            '{"url": "https://github.com/a/b", "branch": "main", "name": "test"}'
            ']}')
        repos = load_repos(str(config))
        assert repos[0].description == ""
