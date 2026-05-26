"""CLI for the single-query live RAG debug harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tests.rag_eval.query_debug import DEFAULT_LOTO_QUERY, QueryDebugOptions, run_query_debug
from tests.rag_eval.variants import DEFAULT_VARIANT_ID, RUN_1_VARIANT_IDS


def _parse_args(argv: list[str] | None = None) -> QueryDebugOptions:
    parser = argparse.ArgumentParser(description="Run one live RAG query and write citation/debug artifacts.")
    parser.add_argument("--query", default=DEFAULT_LOTO_QUERY, help="Question to send through the live RAG pipeline.")
    parser.add_argument("--case-id", default="manual-loto-procedure", help="Artifact filename stem.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("test-artifacts") / "rag-query-debug",
        help="Output root for artifacts.",
    )
    parser.add_argument("--run-id", default=None, help="Optional stable run id.")
    parser.add_argument("--variant", default=DEFAULT_VARIANT_ID, choices=RUN_1_VARIANT_IDS)
    parser.add_argument("--retrieval-top-n", type=int, default=10)
    args = parser.parse_args(argv)
    return QueryDebugOptions(
        query=args.query,
        case_id=args.case_id,
        output_root=args.output,
        run_id=args.run_id,
        variant_id=args.variant,
        retrieval_top_n=args.retrieval_top_n,
    )


def main(argv: list[str] | None = None) -> int:
    summary = run_query_debug(_parse_args(argv))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 1 if summary.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
