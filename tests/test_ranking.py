"""Tests for conclave.ranking — parse_ranking, aggregate_rankings, build_critique_prompt,
and JSON-based ranking extraction."""

import json

import pytest

from conclave.ranking import (
    LETTERS,
    aggregate_rankings,
    build_critique_prompt,
    build_repair_prompt,
    extract_json_ranking,
    parse_ranking,
    parse_ranking_json,
    validate_ranking,
)


# ── parse_ranking: numbered lists ──────────────────────────────────


class TestParseRankingNumbered:
    def test_simple_numbered(self):
        text = "Some analysis.\n\nFINAL RANKING:\n1. A\n2. B\n3. C\n"
        assert parse_ranking(text) == ["A", "B", "C"]

    def test_numbered_with_response_prefix(self):
        text = "...\n\nFINAL RANKING:\n1. Response A\n2. Response B\n3. Response C\n"
        assert parse_ranking(text) == ["A", "B", "C"]

    def test_numbered_with_bold(self):
        text = "...\n\nFINAL RANKING:\n1. **A** - best\n2. **B** - ok\n3. **C** - weak\n"
        assert parse_ranking(text) == ["A", "B", "C"]

    def test_numbered_parenthesis_style(self):
        text = "...\n\nFINAL RANKING:\n1) A\n2) B\n3) C\n"
        assert parse_ranking(text) == ["A", "B", "C"]

    def test_numbered_colon_style(self):
        text = "...\n\nFINAL RANKING:\n1: A\n2: B\n"
        assert parse_ranking(text) == ["A", "B"]

    def test_numbered_dash_style(self):
        text = "...\n\nFINAL RANKING:\n1- A\n2- B\n3- C\n"
        assert parse_ranking(text) == ["A", "B", "C"]

    def test_numbered_with_brackets(self):
        text = "...\n\nFINAL RANKING:\n1. [A]\n2. [B]\n3. [C]\n"
        assert parse_ranking(text) == ["A", "B", "C"]

    def test_deduplicates(self):
        """If model repeats a letter, it should appear only once."""
        text = "...\n\nFINAL RANKING:\n1. A\n2. B\n3. A\n4. C\n"
        assert parse_ranking(text) == ["A", "B", "C"]


# ── parse_ranking: inline arrows ──────────────────────────────────


class TestParseRankingArrows:
    def test_greater_than(self):
        text = "...\n\nFINAL RANKING:\nA > B > C\n"
        assert parse_ranking(text) == ["A", "B", "C"]

    def test_unicode_arrow(self):
        text = "...\n\nFINAL RANKING:\nB → A → C\n"
        assert parse_ranking(text) == ["B", "A", "C"]

    def test_double_greater_than(self):
        text = "...\n\nFINAL RANKING:\nC >> A >> B\n"
        assert parse_ranking(text) == ["C", "A", "B"]


# ── parse_ranking: comma-separated ────────────────────────────────


class TestParseRankingComma:
    def test_comma_separated(self):
        text = "...\n\nFINAL RANKING:\nA, B, C\n"
        assert parse_ranking(text) == ["A", "B", "C"]

    def test_comma_with_spaces(self):
        text = "...\n\nFINAL RANKING:\n B , A , C \n"
        assert parse_ranking(text) == ["B", "A", "C"]


# ── parse_ranking: standalone letters ─────────────────────────────


class TestParseRankingStandalone:
    def test_standalone_plain(self):
        text = "...\n\nFINAL RANKING:\nB\nA\nC\n"
        assert parse_ranking(text) == ["B", "A", "C"]

    def test_standalone_bold(self):
        text = "...\n\nFINAL RANKING:\n**A**\n**C**\n**B**\n"
        assert parse_ranking(text) == ["A", "C", "B"]

    def test_standalone_brackets(self):
        text = "...\n\nFINAL RANKING:\n[A]\n[B]\n"
        assert parse_ranking(text) == ["A", "B"]


# ── parse_ranking: header variations ──────────────────────────────


class TestParseRankingHeaders:
    def test_markdown_header(self):
        text = "...\n\n## Final Ranking\n1. A\n2. B\n"
        assert parse_ranking(text) == ["A", "B"]

    def test_bold_header(self):
        text = "...\n\n**FINAL RANKING:**\n1. B\n2. A\n"
        assert parse_ranking(text) == ["B", "A"]

    def test_just_ranking_word(self):
        text = "...\n\nRanking:\n1. C\n2. A\n3. B\n"
        assert parse_ranking(text) == ["C", "A", "B"]

    def test_lowercase_ranking(self):
        text = "...\n\nranking:\n1. A\n2. B\n"
        assert parse_ranking(text) == ["A", "B"]


# ── parse_ranking: edge cases ─────────────────────────────────────


class TestParseRankingEdgeCases:
    def test_no_ranking_header(self):
        assert parse_ranking("Just some text without any ranking section.") == []

    def test_empty_string(self):
        assert parse_ranking("") == []

    def test_ranking_header_but_no_letters(self):
        text = "...\n\nFINAL RANKING:\nNo clear ranking here.\n"
        assert parse_ranking(text) == []

    def test_only_one_standalone_letter(self):
        """Need at least 2 letters for standalone strategy."""
        text = "...\n\nFINAL RANKING:\nA\n"
        assert parse_ranking(text) == []

    def test_realistic_critique(self):
        """Full realistic critique text from an LLM."""
        text = (
            "## Critique\n\n"
            "Response A provides a thorough analysis of PostgreSQL's strengths...\n"
            "Response B focuses on MongoDB but overlooks ACID guarantees...\n"
            "Response C suggests a hybrid approach which is pragmatic...\n\n"
            "**FINAL RANKING:**\n"
            "1. Response C - most balanced\n"
            "2. Response A - solid but narrow\n"
            "3. Response B - incomplete analysis\n"
        )
        assert parse_ranking(text) == ["C", "A", "B"]


# ── aggregate_rankings ────────────────────────────────────────────


class TestAggregateRankings:
    def test_basic_aggregation(self):
        critiques = [
            {"ranking": ["A", "B", "C"], "letter_map": {"A": "claude", "B": "gemini", "C": "gpt"}},
            {"ranking": ["B", "A", "C"], "letter_map": {"A": "claude", "B": "gemini", "C": "gpt"}},
        ]
        result = aggregate_rankings(critiques)
        assert result["claude"] == 1.5   # positions 1, 2 → avg 1.5
        assert result["gemini"] == 1.5   # positions 2, 1 → avg 1.5
        assert result["gpt"] == 3.0      # positions 3, 3 → avg 3.0

    def test_sorted_by_average(self):
        critiques = [
            {"ranking": ["A", "B", "C"], "letter_map": {"A": "gpt", "B": "claude", "C": "gemini"}},
            {"ranking": ["A", "C", "B"], "letter_map": {"A": "gpt", "B": "claude", "C": "gemini"}},
        ]
        result = aggregate_rankings(critiques)
        keys = list(result.keys())
        assert keys[0] == "gpt"  # avg 1.0 → first

    def test_skips_errors(self):
        critiques = [
            {"error": "timeout", "ranking": ["A", "B"], "letter_map": {"A": "x", "B": "y"}},
            {"ranking": ["A", "B"], "letter_map": {"A": "claude", "B": "gemini"}},
        ]
        result = aggregate_rankings(critiques)
        assert "x" not in result
        assert "claude" in result

    def test_skips_missing_ranking(self):
        critiques = [
            {"letter_map": {"A": "claude"}},  # no "ranking" key
            {"ranking": ["A", "B"], "letter_map": {"A": "claude", "B": "gemini"}},
        ]
        result = aggregate_rankings(critiques)
        assert result["claude"] == 1.0
        assert result["gemini"] == 2.0

    def test_empty_critiques(self):
        assert aggregate_rankings([]) == {}


# ── build_critique_prompt ─────────────────────────────────────────


class TestBuildCritiquePrompt:
    @pytest.fixture
    def drafts(self):
        return [
            {"key": "claude", "content": "Claude's answer"},
            {"key": "gemini", "content": "Gemini's answer"},
            {"key": "gpt", "content": "GPT's answer"},
        ]

    @pytest.fixture
    def templates(self):
        return {
            "critique_prompt": "Q: {original_prompt}\n\n{anonymized_responses}",
        }

    def test_excludes_self(self, drafts, templates):
        prompt, letter_map = build_critique_prompt(
            "test question", drafts, "claude", anonymize=False, templates=templates)
        # Claude excluded → only gemini and gpt in letter_map
        assert "claude" not in letter_map.values()
        assert len(letter_map) == 2
        assert "Claude's answer" not in prompt

    def test_letter_map_uses_uppercase(self, drafts, templates):
        _, letter_map = build_critique_prompt(
            "test", drafts, "claude", anonymize=False, templates=templates)
        for letter in letter_map:
            assert letter in LETTERS

    def test_includes_original_prompt(self, drafts, templates):
        prompt, _ = build_critique_prompt(
            "What is REST?", drafts, "gpt", anonymize=False, templates=templates)
        assert "What is REST?" in prompt

    def test_excludes_errored_drafts(self, templates):
        drafts = [
            {"key": "claude", "content": "OK"},
            {"key": "gemini", "error": "timeout"},
            {"key": "gpt", "content": "Also OK"},
        ]
        _, letter_map = build_critique_prompt(
            "test", drafts, "claude", anonymize=False, templates=templates)
        assert "gemini" not in letter_map.values()
        assert len(letter_map) == 1  # only gpt (claude excluded as self)

    def test_anonymize_does_not_crash(self, drafts, templates):
        """Anonymize shuffles — just verify it returns valid data."""
        prompt, letter_map = build_critique_prompt(
            "test", drafts, "claude", anonymize=True, templates=templates)
        assert len(letter_map) == 2
        assert prompt  # non-empty


# ── extract_json_ranking ─────────────────────────────────────────


class TestExtractJsonRanking:
    def test_fenced_json_block(self):
        text = 'Some critique.\n\n```json\n{"ranking": ["A", "B", "C"]}\n```\n'
        result = extract_json_ranking(text)
        assert result == {"ranking": ["A", "B", "C"]}

    def test_bare_json(self):
        text = 'Here is my ranking: {"ranking": ["B", "A", "C"]}'
        result = extract_json_ranking(text)
        assert result == {"ranking": ["B", "A", "C"]}

    def test_no_json(self):
        text = "Just a plain text critique with no JSON at all."
        assert extract_json_ranking(text) is None

    def test_invalid_json(self):
        text = '```json\n{"ranking": ["A", "B",]}\n```'
        assert extract_json_ranking(text) is None

    def test_json_without_ranking_key(self):
        text = '```json\n{"scores": [1, 2, 3]}\n```'
        assert extract_json_ranking(text) is None

    def test_multiple_fenced_blocks_picks_first_with_ranking(self):
        text = (
            '```json\n{"other": true}\n```\n'
            '```json\n{"ranking": ["C", "A"]}\n```\n'
        )
        result = extract_json_ranking(text)
        assert result == {"ranking": ["C", "A"]}

    def test_fenced_with_whitespace(self):
        text = '```json\n  \n  {"ranking": ["A", "B"]}  \n\n```'
        result = extract_json_ranking(text)
        assert result == {"ranking": ["A", "B"]}

    def test_bare_json_picks_last(self):
        text = (
            'First: {"ranking": ["A", "B"]} '
            'Then revised: {"ranking": ["B", "A"]}'
        )
        result = extract_json_ranking(text)
        assert result == {"ranking": ["B", "A"]}

    def test_fenced_preferred_over_bare(self):
        text = (
            'Bare: {"ranking": ["X", "Y"]}\n'
            '```json\n{"ranking": ["A", "B"]}\n```\n'
        )
        result = extract_json_ranking(text)
        assert result == {"ranking": ["A", "B"]}


# ── validate_ranking ─────────────────────────────────────────────


class TestValidateRanking:
    def test_valid(self):
        obj = {"ranking": ["A", "B", "C"]}
        result = validate_ranking(obj, {"A", "B", "C"})
        assert result == ["A", "B", "C"]

    def test_two_items(self):
        obj = {"ranking": ["B", "A"]}
        result = validate_ranking(obj, {"A", "B"})
        assert result == ["B", "A"]

    def test_missing_key(self):
        obj = {"scores": [1, 2]}
        assert validate_ranking(obj, {"A", "B"}) is None

    def test_non_list(self):
        obj = {"ranking": "A, B, C"}
        assert validate_ranking(obj, {"A", "B", "C"}) is None

    def test_fewer_than_2(self):
        obj = {"ranking": ["A"]}
        assert validate_ranking(obj, {"A", "B"}) is None

    def test_invalid_letters(self):
        obj = {"ranking": ["A", "B", "X"]}
        assert validate_ranking(obj, {"A", "B", "C"}) is None

    def test_duplicates_removed(self):
        obj = {"ranking": ["A", "B", "A", "C"]}
        result = validate_ranking(obj, {"A", "B", "C"})
        assert result == ["A", "B", "C"]

    def test_non_strings(self):
        obj = {"ranking": [1, 2, 3]}
        assert validate_ranking(obj, {"A", "B", "C"}) is None

    def test_strip_and_uppercase(self):
        obj = {"ranking": [" a ", " b ", " c "]}
        result = validate_ranking(obj, {"A", "B", "C"})
        assert result == ["A", "B", "C"]

    def test_multi_char_rejected(self):
        obj = {"ranking": ["AB", "C"]}
        assert validate_ranking(obj, {"A", "B", "C"}) is None

    def test_not_a_dict(self):
        assert validate_ranking(["A", "B"], {"A", "B"}) is None


# ── parse_ranking_json ───────────────────────────────────────────


class TestParseRankingJson:
    def test_full_pipeline(self):
        text = '```json\n{"ranking": ["B", "A", "C"]}\n```'
        result = parse_ranking_json(text, {"A", "B", "C"})
        assert result == ["B", "A", "C"]

    def test_no_json_returns_empty(self):
        result = parse_ranking_json("no json here", {"A", "B"})
        assert result == []

    def test_invalid_letters_returns_empty(self):
        text = '```json\n{"ranking": ["X", "Y"]}\n```'
        result = parse_ranking_json(text, {"A", "B"})
        assert result == []

    def test_malformed_json_returns_empty(self):
        text = '```json\n{ranking: [A, B]}\n```'
        result = parse_ranking_json(text, {"A", "B"})
        assert result == []


# ── build_repair_prompt ──────────────────────────────────────────


class TestBuildRepairPrompt:
    def test_contains_letters(self):
        prompt = build_repair_prompt({"C", "A", "B"})
        assert "A" in prompt
        assert "B" in prompt
        assert "C" in prompt

    def test_contains_json_example(self):
        prompt = build_repair_prompt({"A", "B"})
        assert '"ranking"' in prompt
        # Should be valid JSON in the example
        assert '["A", "B"]' in prompt

    def test_sorted_letters(self):
        prompt = build_repair_prompt({"C", "A", "B"})
        # The example should have letters in sorted order
        expected = json.dumps({"ranking": ["A", "B", "C"]})
        assert expected in prompt
