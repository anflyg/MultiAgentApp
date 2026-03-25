from __future__ import annotations

import argparse
import json
import os

from .api_server import run_memory_api_server
from .memory_orientation import orient_question_to_memory_by_db


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MultiAgentApp ChatGPT-first memory backend CLI.")
    parser.add_argument(
        "--db-path",
        default="multi_agent.db",
        help="Path to SQLite database file.",
    )
    subparsers = parser.add_subparsers(dest="command")

    orient_parser = subparsers.add_parser(
        "memory-orient",
        help="Run memory orientation for one question.",
    )
    orient_parser.add_argument("--question", required=True, help="Question to orient.")
    orient_parser.add_argument("--workspace-id", help="Optional workspace scope override.")
    orient_parser.add_argument("--limit", type=int, default=3, help="Max number of matches.")

    serve_api_parser = subparsers.add_parser(
        "serve-memory-api",
        help="Run local HTTP API for memory orientation/read/search.",
    )
    serve_api_parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    serve_api_parser.add_argument("--port", type=int, default=8001, help="Bind port.")
    serve_api_parser.add_argument(
        "--api-token",
        default=None,
        help="Optional bearer token. If omitted, uses MULTI_AGENT_APP_API_TOKEN.",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "memory-orient":
        try:
            result = orient_question_to_memory_by_db(
                args.db_path,
                question=args.question,
                workspace_id=args.workspace_id,
                limit=args.limit,
            )
        except ValueError as exc:
            print(f"Memory orientation failed: {exc}")
            raise SystemExit(1) from exc
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
        return

    if args.command == "serve-memory-api":
        token = args.api_token if args.api_token is not None else os.getenv("MULTI_AGENT_APP_API_TOKEN")
        print(
            f"Starting memory API on http://{args.host}:{args.port} "
            f"(db={args.db_path}, auth={'on' if token else 'off'})"
        )
        run_memory_api_server(
            db_path=args.db_path,
            host=args.host,
            port=args.port,
            api_token=token,
        )
        return

    parser.print_help()
