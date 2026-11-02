"""Synthetic document retrieval and deterministic fake-answer comparison."""

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, TypedDict, cast

import psycopg
from psycopg.rows import dict_row

from fake_llm import Evidence, fake_answer

ROOT = Path(__file__).resolve().parent
STOP_WORDS = set(
    "a an the and or is are do does i my can how what when where which "
    "to of on in for it by from much should take".split()
)


class Hit(Evidence):
    score: float


class Question(TypedDict):
    id: str
    text: str
    expected: list[str]


def split_documents(directory: Path) -> list[Evidence]:
    """Split nonempty paragraphs; identify each by source filename + ordinal."""
    passages: list[Evidence] = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        for index, paragraph in enumerate(re.split(r"\n\s*\n", text), start=1):
            if paragraph.strip():
                passages.append(
                    Evidence(
                        passage_id=f"{path.name}#p{index}",
                        source_id=path.name,
                        text=" ".join(paragraph.split()),
                    )
                )
    if not passages:
        raise ValueError(f"No passages found in {directory}")
    return passages


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOP_WORDS


def keyword_search(passages: list[Evidence], question: str) -> list[Hit]:
    query = tokens(question)
    hits = [Hit(**p, score=len(query & tokens(p["text"]))) for p in passages]
    return sorted(
        (h for h in hits if h["score"]), key=lambda h: (-h["score"], h["passage_id"])
    )[:3]


def postgres_search(
    passages: list[Evidence], questions: list[Question], database_url: str
) -> tuple[str, dict[str, list[Hit]]]:
    """Bind fixture values through psycopg; roll back even on failure."""
    with psycopg.connect(database_url, connect_timeout=5) as conn:
        try:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SET LOCAL statement_timeout = '10s'")
                cur.execute("SHOW server_version")
                version = cur.fetchone()
                assert version is not None
                cur.execute("""
                    CREATE TEMP TABLE retrieval_passages (
                        passage_id text PRIMARY KEY, source_id text NOT NULL,
                        body text NOT NULL,
                        document tsvector GENERATED ALWAYS AS
                            (to_tsvector('english', body)) STORED
                    )
                """)
                cur.executemany(
                    "INSERT INTO retrieval_passages (passage_id, source_id, body) "
                    "VALUES (%s, %s, %s)",
                    [(p["passage_id"], p["source_id"], p["text"]) for p in passages],
                )
                results: dict[str, list[Hit]] = {}
                for q in questions:
                    cur.execute(
                        """
                        SELECT passage_id, source_id, body AS text,
                               ts_rank_cd(document, query) AS score
                        FROM retrieval_passages,
                             plainto_tsquery('english', %s) AS query
                        WHERE document @@ query
                        ORDER BY score DESC, passage_id LIMIT 3
                        """,
                        (q["text"],),
                    )
                    results[q["id"]] = cast(list[Hit], cur.fetchall())
                return str(version["server_version"]), results
        finally:
            conn.rollback()


def evaluate(
    questions: list[Question], results: dict[str, list[Hit]]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for q in questions:
        hits = results[q["id"]]
        actual = {h["passage_id"] for h in hits}
        expected = set(q["expected"])
        # No corpus, expected labels, or question ID crosses the fake boundary.
        evidence = [
            Evidence(
                passage_id=h["passage_id"], source_id=h["source_id"], text=h["text"]
            )
            for h in hits
        ]
        rows.append(
            dict(
                q,
                hits=hits,
                missed=sorted(expected - actual),
                irrelevant=sorted(actual - expected),
                answer=fake_answer(q["text"], evidence),
            )
        )
    supported = [r for r in rows if r["expected"]]
    unsupported = [r for r in rows if not r["expected"]]
    return {
        "supported_hit_at_3": sum(
            bool(set(r["expected"]) & {h["passage_id"] for h in r["hits"]})
            for r in supported
        ),
        "supported_questions": len(supported),
        "unsupported_with_hits": sum(bool(r["hits"]) for r in unsupported),
        "unsupported_questions": len(unsupported),
        "irrelevant_passages": sum(len(r["irrelevant"]) for r in rows),
        "questions": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keyword-only",
        action="store_true",
        help="Debug baseline only; not the full comparison",
    )
    parser.add_argument(
        "--output", type=Path, help="Write JSON here (stdout otherwise)"
    )
    args = parser.parse_args()
    questions = cast(
        list[Question],
        json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))["questions"],
    )
    passages = split_documents(ROOT / "documents")
    keyword = {q["id"]: keyword_search(passages, q["text"]) for q in questions}
    report: dict[str, Any] = {
        "fixture": "fixtures.json",
        "documents": "documents/*.md",
        "splitting": "Nonempty paragraphs; source filename plus #pN ordinal",
        "top_k": 3,
        "passages": passages,
        "keyword": evaluate(questions, keyword),
    }
    if not args.keyword_only:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            parser.exit(
                1,
                "Set DATABASE_URL for the PostgreSQL comparison. No report written.\n",
            )
        try:
            version, results = postgres_search(passages, questions, database_url)
        except psycopg.Error:
            # Avoid printing connection strings or credentials in errors.
            parser.exit(
                1,
                "PostgreSQL comparison failed. Check DATABASE_URL and "
                "database availability. No report written.\n",
            )
        report["postgres_version"] = version
        report["postgres"] = evaluate(questions, results)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
