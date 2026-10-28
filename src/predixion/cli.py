"""Command-line interface.

predixion serve                    run the API (and the built frontend, if configured)
predixion ask "question" [...]     run one research task and print the report
predixion samples                  list fixture sample questions
predixion token --user NAME        create an API token and its config line
predixion eval [...]               run the evaluation suite
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import secrets
import sys
from pathlib import Path

from pydantic import ValidationError

from .config import Settings, get_settings
from .contracts import EventType, Mode, ResearchRequest, RunStatus
from .fixtures import sample_questions
from .orchestrator import Providers, ResearchRun
from .render import render_markdown

EXIT_CODES = {
    RunStatus.completed: 0,
    RunStatus.partial: 0,
    RunStatus.insufficient_evidence: 3,
    RunStatus.failed: 4,
    RunStatus.cancelled: 5,
    RunStatus.interrupted: 5,
}


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    from .api import create_app

    host = args.host or settings.host
    port = args.port or settings.port
    if not _is_loopback(host) and settings.auth_mode == "none" and not settings.allow_unauthenticated_bind:
        print(
            f"Refusing to bind {host} without authentication. Set AUTH_MODE=token with API_TOKEN_HASHES, "
            "or ALLOW_UNAUTHENTICATED_BIND=true if the port is only published on loopback.",
            file=sys.stderr,
        )
        return 2
    uvicorn.run(create_app(settings), host=host, port=port, log_level="warning", proxy_headers=False, server_header=False)
    return 0


def _providers(settings: Settings, mode: Mode, question: str) -> tuple[Providers, list]:
    if mode == Mode.fixture:
        from .fixtures import FixtureExtract, FixtureModel, FixtureSearch, match_scenario

        scenario = match_scenario(question)
        return Providers(FixtureSearch(scenario), FixtureExtract(scenario), FixtureModel(scenario), Mode.fixture), []
    from .llm import live_routes
    from .tools import TavilyClient

    assert settings.tavily_api_key is not None and settings.openai_api_key is not None
    tavily = TavilyClient(settings.tavily_api_key.get_secret_value())
    routes, models = live_routes(settings)
    return Providers(tavily, tavily, routes.primary, Mode.live, routes=routes), [tavily, *models]


async def run_once(settings: Settings, request: ResearchRequest, mode: Mode, *, quiet: bool = False):
    providers, closers = _providers(settings, mode, request.question)

    def emit(type_: EventType, stage, message: str, data) -> None:
        if quiet:
            return
        if type_ in (EventType.stage, EventType.warning, EventType.error, EventType.coverage):
            label = stage.value if stage else type_.value
            print(f"  [{label}] {message}", file=sys.stderr)

    run = ResearchRun("run_" + secrets.token_hex(12), request, settings, providers, emit)
    try:
        return await run.execute()
    finally:
        for closer in closers:
            await closer.aclose()


def cmd_ask(args: argparse.Namespace, settings: Settings) -> int:
    mode = Mode(args.mode or settings.mode)
    if mode == Mode.live and not settings.live_available:
        print(f"Live mode needs {', '.join(settings.missing_live_credentials())}.", file=sys.stderr)
        return 2
    try:
        request = ResearchRequest(question=args.question, mode=mode, max_rounds=args.max_rounds, seed_urls=args.seed_url or [])
    except ValidationError as exc:
        print(f"Invalid request: {exc.errors()[0]['msg']}", file=sys.stderr)
        return 2
    print(f"Researching ({mode.value} mode)...", file=sys.stderr)
    report = asyncio.run(run_once(settings, request, mode, quiet=args.quiet))
    text = report.model_dump_json(indent=2) if args.json else render_markdown(report)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        print(text)
    m = report.execution.metrics
    print(
        f"Status: {report.status.value} ({report.stop_reason.value if report.stop_reason else '-'}); "
        f"confidence {report.confidence.level.value}; {m.model_calls} model calls; ${m.estimated_cost_usd:.4f}",
        file=sys.stderr,
    )
    return EXIT_CODES.get(report.status, 1)


def cmd_samples(_: argparse.Namespace, __: Settings) -> int:
    for s in sample_questions():
        print(f"{s['id']:<24} {s['question']}")
    return 0


def cmd_token(args: argparse.Namespace, _: Settings) -> int:
    import hashlib

    if not args.user.replace("-", "").replace("_", "").isalnum():
        print("User id may contain letters, digits, '-' and '_' only.", file=sys.stderr)
        return 2
    token = "pdx_" + secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    print("Token (give this to the user; it is not stored anywhere):", file=sys.stderr)
    print(token)
    print("\nAdd to API_TOKEN_HASHES (comma-separate multiple users):", file=sys.stderr)
    print(f"{args.user}:{digest}")
    return 0


def cmd_eval(args: argparse.Namespace, settings: Settings) -> int:
    from .evals import main as eval_main

    return eval_main(args, settings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="predixion", description="Predixion AI research agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="run the API server")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("ask", help="research one question")
    p.add_argument("question")
    p.add_argument("--mode", choices=[m.value for m in Mode])
    p.add_argument("--max-rounds", type=int, choices=[1, 2, 3, 4])
    p.add_argument("--seed-url", action="append", help="URL to read first (repeatable, max 3)")
    p.add_argument("--json", action="store_true", help="print the full report as JSON")
    p.add_argument("--out", help="write the report to a file")
    p.add_argument("--quiet", action="store_true", help="no progress output")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("samples", help="list fixture sample questions")
    p.set_defaults(func=cmd_samples)

    p = sub.add_parser("token", help="create an API token")
    p.add_argument("--user", required=True)
    p.set_defaults(func=cmd_token)

    p = sub.add_parser("eval", help="run the evaluation suite")
    p.add_argument("--mode", choices=[m.value for m in Mode], default="fixture")
    p.add_argument("--scenario", action="append", help="run only these scenario ids")
    p.add_argument("--model", help="override RESEARCH_MODEL for live runs")
    p.add_argument("--no-baseline", action="store_true", help="skip the one-pass baseline")
    p.add_argument("--max-spend", type=float, default=3.0, help="stop live evaluation at this estimated USD spend")
    p.add_argument("--input-usd-per-mtok", type=float, help="input price for --model (USD per million tokens)")
    p.add_argument("--output-usd-per-mtok", type=float, help="output price for --model (USD per million tokens)")
    p.add_argument("--out", help="write results JSON here")
    p.add_argument("--save-reports", metavar="DIR", help="also write each agent report as JSON into DIR")
    p.set_defaults(func=cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    return args.func(args, settings)


if __name__ == "__main__":
    sys.exit(main())
