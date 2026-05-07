"""Unit tests for _split_compound_intent.

Tests are grouped into:
  - MUST-SPLIT:  inputs that should produce multiple clauses
  - MUST-NOT-SPLIT:  inputs that should remain a single clause
  - EDGE CASES:  empty, whitespace, punctuation edge cases
"""

from __future__ import annotations

import pytest

from agent.planner import _split_compound_intent


# ────────────────────────────────────────────────────────
# MUST-SPLIT — these should produce ≥ 2 clauses
# ────────────────────────────────────────────────────────

class TestMustSplit:
    """Inputs that are clearly multi-action and MUST be split."""

    # ── Tier 1: explicit sequencing connectors ──

    def test_and_then_connector(self):
        result = _split_compound_intent("Check machine M-LTH-02 status and then show slots for JOB-SEED-001")
        assert len(result) == 2
        assert "machine" in result[0].lower()
        assert "slots" in result[1].lower()

    def test_then_connector(self):
        result = _split_compound_intent("show all jobs then approve JOB-42")
        assert len(result) == 2

    def test_next_connector(self):
        result = _split_compound_intent("list machines next update machine M-01")
        assert len(result) == 2

    def test_after_that_connector(self):
        result = _split_compound_intent("get job JOB-01 after that delete it")
        assert len(result) == 2

    def test_finally_connector(self):
        result = _split_compound_intent("check job JOB-01 finally approve it")
        assert len(result) == 2

    def test_semicolon_separator(self):
        result = _split_compound_intent("show jobs; check machine M-01")
        assert len(result) == 2

    def test_period_separator(self):
        result = _split_compound_intent("Show all jobs. Check machine M-01 status.")
        assert len(result) >= 2

    def test_newline_separator(self):
        result = _split_compound_intent("show all jobs\ncheck machine M-01")
        assert len(result) == 2

    # ── Tier 2: "and"/"also" with distinct action verbs ──

    def test_and_with_two_action_verbs(self):
        result = _split_compound_intent("show all pending jobs and approve JOB-42")
        assert len(result) == 2

    def test_also_with_two_action_verbs(self):
        result = _split_compound_intent("list machines also check job JOB-01")
        assert len(result) == 2

    def test_and_show_and_update(self):
        result = _split_compound_intent("show machine M-01 and update its status")
        assert len(result) == 2

    # ── NEW: comma-separated with distinct action verbs ──

    def test_comma_with_two_action_verbs(self):
        result = _split_compound_intent("list all jobs, check machine M-01")
        assert len(result) == 2

    def test_comma_show_and_approve(self):
        result = _split_compound_intent("show pending jobs, approve JOB-42")
        assert len(result) == 2

    def test_comma_three_actions(self):
        result = _split_compound_intent("show jobs, list machines, check materials")
        assert len(result) == 3

    # ── NEW: "but first" / "before that" / "once done" / "when done" ──

    def test_but_first_connector(self):
        result = _split_compound_intent("approve JOB-42 but first check its status")
        assert len(result) == 2

    def test_once_done_connector(self):
        result = _split_compound_intent("check machine M-01 once done show all jobs")
        assert len(result) == 2

    # ── NEW: numbered steps ──

    def test_numbered_steps(self):
        result = _split_compound_intent("1. show all jobs 2. check machine M-01 3. list materials")
        assert len(result) == 3

    def test_numbered_steps_with_parenthesis(self):
        result = _split_compound_intent("1) show all jobs 2) check machine M-01")
        assert len(result) == 2

    # ── Three-clause splits ──

    def test_three_clauses_with_then(self):
        result = _split_compound_intent("show jobs then check machine M-01 then list materials")
        assert len(result) == 3

    def test_three_clauses_semicolons(self):
        result = _split_compound_intent("show jobs; check machine; list materials")
        assert len(result) == 3


# ────────────────────────────────────────────────────────
# MUST-NOT-SPLIT — these should remain a single clause
# ────────────────────────────────────────────────────────

class TestMustNotSplit:
    """Inputs that look like they have connectors but are actually single operations."""

    def test_noun_phrase_with_and(self):
        """'jobs and machines' is a list of nouns, not two actions."""
        result = _split_compound_intent("show all jobs and machines")
        assert len(result) == 1

    def test_show_status_and_slots(self):
        """Entity sub-resources connected by 'and' — single query intent."""
        result = _split_compound_intent("show status and slots for JOB-42")
        assert len(result) == 1

    def test_simple_single_command(self):
        result = _split_compound_intent("show all pending jobs")
        assert len(result) == 1

    def test_single_id_lookup(self):
        result = _split_compound_intent("check machine M-LTH-02")
        assert len(result) == 1

    def test_simple_approval(self):
        result = _split_compound_intent("approve JOB-42")
        assert len(result) == 1

    def test_reason_clause_with_and(self):
        """'and' in a reason/because clause should NOT split."""
        result = _split_compound_intent("approve JOB-42 because the line is ready and it needs to start")
        assert len(result) == 1

    def test_filter_with_and(self):
        """'and' connecting filter values should NOT split."""
        result = _split_compound_intent("show jobs with status pending and priority high")
        assert len(result) == 1

    def test_entity_name_with_and(self):
        """Entity names containing 'and' should NOT cause a split."""
        result = _split_compound_intent("check machine Assembly-Line-And-Pack-01")
        assert len(result) == 1

    def test_empty_input(self):
        result = _split_compound_intent("")
        assert result == [""]

    def test_whitespace_only(self):
        result = _split_compound_intent("   ")
        assert result == [""]

    def test_single_word(self):
        result = _split_compound_intent("jobs")
        assert len(result) == 1

    def test_enumeration_without_verbs(self):
        """A list of entities (no separate action verbs) stays as 1 clause."""
        result = _split_compound_intent("show me jobs, machines, and materials")
        assert len(result) == 1

    def test_location_with_comma(self):
        """Comma inside a location name should NOT split."""
        result = _split_compound_intent("show jobs in Assembly Line 3, Building A")
        assert len(result) == 1

    def test_id_with_period(self):
        """Period inside a version-like ID should NOT split (e.g. v2.1)."""
        result = _split_compound_intent("check firmware v2.1 for machine M-01")
        assert len(result) == 1


# ────────────────────────────────────────────────────────
# EDGE CASES
# ────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_trailing_period_does_not_create_empty(self):
        result = _split_compound_intent("show all jobs.")
        assert result == ["show all jobs"]

    def test_multiple_spaces_normalized(self):
        result = _split_compound_intent("show   all   jobs   and then   check  machine  M-01")
        assert len(result) == 2

    def test_mixed_separators(self):
        result = _split_compound_intent("show jobs; then check machine M-01. finally list materials")
        assert len(result) >= 3

    def test_preserves_ids_in_clauses(self):
        result = _split_compound_intent("check machine M-LTH-02 and then show slots for JOB-SEED-001")
        assert "M-LTH-02" in result[0]
        assert "JOB-SEED-001" in result[1]
