"""Standalone, synthetic retrieval comparison. Python standard library + psql only."""

import argparse
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parent
# Deliberately small, fixed baseline list; no stemming or synonym expansion.
STOP_WORDS = set("a an the and or is are do does i my can how what when where which "
                 "to of on in for it by from much should take".split())


def tokens(text):
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOP_WORDS


def keyword_search(passages, question):
    query = tokens(question)
    hits = [dict(p, score=len(query & tokens(p["text"]))) for p in passages]
    return sorted((h for h in hits if h["score"]),
                  key=lambda h: (-h["score"], h["passage_id"]))[:3]


def literal(value):
    # Fixtures are text literals, never SQL identifiers. Also escape backslashes
    # explicitly so behavior does not depend on standard_conforming_strings.
    return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def postgres_search(fixture, command):
    passages = ",\n".join("(" + ",".join(literal(p[k]) for k in
                           ("passage_id", "source_id", "text")) + ")"
                           for p in fixture["passages"])
    questions = ",\n".join(f"({literal(q['id'])},{literal(q['text'])})"
                            for q in fixture["questions"])
    sql = f"""
BEGIN;
CREATE TEMP TABLE retrieval_passages (
    passage_id text PRIMARY KEY, source_id text NOT NULL, body text NOT NULL,
    document tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED
);
INSERT INTO retrieval_passages (passage_id, source_id, body) VALUES {passages};
WITH questions(id, question) AS (VALUES {questions}),
queries AS (
    SELECT id, plainto_tsquery('english', question) AS query FROM questions
)
SELECT json_build_object(
    'server_version', current_setting('server_version'),
    'results', (SELECT json_object_agg(id, hits) FROM (
        SELECT id, COALESCE((
            SELECT json_agg(row_to_json(hit)) FROM (
                SELECT passage_id, source_id, body AS text,
                       ts_rank_cd(document, query) AS score
                FROM retrieval_passages WHERE document @@ query
                ORDER BY score DESC, passage_id LIMIT 3
            ) hit
        ), '[]'::json) AS hits FROM queries
    ) answers)
);
ROLLBACK;
"""
    result = subprocess.run(command + ["-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
                            input=sql, text=True, encoding="utf-8", capture_output=True,
                            timeout=60, check=True)
    return json.loads(result.stdout)


def evaluate(questions, results):
    rows = []
    for q in questions:
        hits = results[q["id"]]
        actual = {h["passage_id"] for h in hits}
        expected = set(q["expected"])
        rows.append(dict(q, hits=hits, missed=sorted(expected - actual),
                         irrelevant=sorted(actual - expected)))
    supported = [r for r in rows if r["expected"]]
    unsupported = [r for r in rows if not r["expected"]]
    return {
        "supported_hit_at_3": sum(bool(set(r["expected"]) &
                                        {h["passage_id"] for h in r["hits"]})
                                  for r in supported),
        "supported_questions": len(supported),
        "unsupported_with_hits": sum(bool(r["hits"]) for r in unsupported),
        "unsupported_questions": len(unsupported),
        "irrelevant_passages": sum(len(r["irrelevant"]) for r in rows),
        "questions": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    backend = parser.add_mutually_exclusive_group()
    backend.add_argument("--container", help="Run psql inside this running Docker container")
    backend.add_argument("--keyword-only", action="store_true",
                         help="Debug baseline only; does not complete the comparison")
    parser.add_argument("--psql", default="psql", help="Path to local psql executable")
    parser.add_argument("--output", type=Path, help="Write JSON here (stdout otherwise)")
    args = parser.parse_args()
    fixture = json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))
    keyword = {q["id"]: keyword_search(fixture["passages"], q["text"])
               for q in fixture["questions"]}
    report = {"fixture": "fixtures.json", "top_k": 3,
              "keyword": evaluate(fixture["questions"], keyword)}
    if not args.keyword_only:
        command = (["docker", "exec", "-i", args.container, "psql", "-U", "postgres",
                    "-d", "postgres"] if args.container else [args.psql])
        try:
            postgres = postgres_search(fixture, command)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            parser.exit(1, f"PostgreSQL comparison failed: {exc}\n"
                        "Check psql/PG* settings or the Docker container. No report written.\n")
        report["postgres_version"] = postgres["server_version"]
        report["postgres"] = evaluate(fixture["questions"], postgres["results"])
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
