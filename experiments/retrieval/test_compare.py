"""Unit checks for the comparison harness, not a substitute for a PostgreSQL run."""

import unittest

from compare import evaluate, keyword_search, literal


class ComparisonTests(unittest.TestCase):
    def test_keyword_keeps_sources_and_uses_whole_words(self):
        passage = {"passage_id": "p1", "source_id": "original.md", "text": "Parking"}
        self.assertEqual(keyword_search([passage], "park"), [])
        self.assertEqual(keyword_search([passage], "Is parking available?")[0]["source_id"],
                         "original.md")
        self.assertEqual(keyword_search([passage], "the and is"), [])

    def test_metrics_distinguish_misses_and_unsupported_hits(self):
        questions = [{"id": "a", "expected": ["p1"]},
                     {"id": "b", "expected": []}]
        hit = {"passage_id": "p2", "source_id": "other.md"}
        report = evaluate(questions, {"a": [], "b": [hit]})
        self.assertEqual(report["supported_hit_at_3"], 0)
        self.assertEqual(report["unsupported_with_hits"], 1)
        self.assertEqual(report["questions"][0]["missed"], ["p1"])
        self.assertEqual(report["questions"][1]["irrelevant"], ["p2"])

    def test_deterministic_top_three(self):
        passages = [{"passage_id": str(i), "text": "clinic"} for i in range(5, 0, -1)]
        self.assertEqual([p["passage_id"] for p in keyword_search(passages, "clinic")],
                         ["1", "2", "3"])

    def test_sql_literal_escapes_quotes_and_backslashes(self):
        self.assertEqual(literal("clinic's\\hours"), "E'clinic''s\\\\hours'")


if __name__ == "__main__":
    unittest.main()
