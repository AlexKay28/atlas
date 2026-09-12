"""Command-line interface for tikhon (docs/spec/02-command-catalog.md).

Commands: lint, seal, run, status, events.
Uses argparse and the standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any, Mapping

from tikhon.registry import builtin_registry
from tikhon.runtime import DeterministicWorker, EventStore, EventType, SequentialCoordinator
from tikhon.syntax import ParseError, parse_program, seal_digest, validate_program


def _load_source(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _builtin_command_names() -> set[str]:
    return set(builtin_registry().names())


def _deterministic_handlers() -> dict[str, Any]:
    def _define(**kwargs: Any) -> Any:
        if "value" in kwargs:
            return kwargs["value"]
        if "request" in kwargs:
            return kwargs["request"]
        return dict(kwargs)

    def _search(**kwargs: Any) -> Any:
        return kwargs.get("query", "")

    def _fetch(**kwargs: Any) -> Any:
        return kwargs.get("resource_refs", kwargs)

    def _extract(**kwargs: Any) -> Any:
        return kwargs.get("artifact", kwargs)

    def _summarize(**kwargs: Any) -> Any:
        return kwargs.get("source_refs", kwargs)

    def _report(**kwargs: Any) -> Any:
        return kwargs.get("committed_refs", kwargs)

    def _verify(**kwargs: Any) -> Any:
        return kwargs.get("goal", kwargs)

    def _calculate(**kwargs: Any) -> Any:
        total = 0
        for val in kwargs.values():
            if isinstance(val, (int, float)):
                total += val
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, (int, float)):
                        total += item
        return total

    def _check(**kwargs: Any) -> Any:
        return kwargs.get("artifact", kwargs)

    return {
        "define": _define,
        "search": _search,
        "fetch": _fetch,
        "extract": _extract,
        "summarize": _summarize,
        "report": _report,
        "verify": _verify,
        "calculate": _calculate,
        "check": _check,
    }


def _cmd_lint(args: argparse.Namespace) -> int:
    try:
        text = _load_source(args.program)
        program = parse_program(text)
        validate_program(program, known_commands=_builtin_command_names())
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("valid")
    return 0


def _cmd_seal(args: argparse.Namespace) -> int:
    try:
        text = _load_source(args.program)
        program = parse_program(text)
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(seal_digest(program))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    if not args.seal:
        print("error: --seal is required for run", file=sys.stderr)
        return 1

    try:
        text = _load_source(args.program)
        program = parse_program(text)
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    actual_digest = seal_digest(program)
    if args.seal != actual_digest:
        print(
            f"error: seal digest mismatch: expected {actual_digest}, got {args.seal}",
            file=sys.stderr,
        )
        return 1

    try:
        store = EventStore(args.db)
    except Exception as exc:
        print(f"error: cannot open event store: {exc}", file=sys.stderr)
        return 1

    worker = DeterministicWorker(_deterministic_handlers())
    coordinator = SequentialCoordinator(store, worker)

    try:
        result = coordinator.execute(program, run_id=args.run_id)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        store.close()
        return 1
    finally:
        store.close()

    status = result.get("status", "unknown")
    print(status)
    if status == "succeeded":
        print("100%")
    return 0 if status == "succeeded" else 1


def _cmd_status(args: argparse.Namespace) -> int:
    try:
        store = EventStore(args.db)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        run_info = store.run(args.run_id)
    except KeyError:
        print(f"error: unknown run: {args.run_id}", file=sys.stderr)
        store.close()
        return 1

    ledger = store.task_ledger(args.run_id)
    profile = ledger.profile()
    store.close()

    total = profile["counts"]["total"]
    completed = profile["counts"]["completed"]
    percent = profile["percent_complete"]
    current_task = profile["current_task"]

    bar_width = 20
    filled = int(bar_width * completed / total) if total else 0
    bar = "=" * filled + "-" * (bar_width - filled)
    print(f"[{bar}] {percent:.0f}% completed {completed}/{total}")
    if current_task:
        task = ledger.tasks.get(current_task)
        task_text = task.text if task else current_task
        print(f"current task: {task_text}")
    elif total > 0 and completed == total:
        last_task = list(ledger.tasks.values())[-1]
        print(f"current task: {last_task.text}")
    else:
        print("current task: (none)")
    return 0


def _cmd_events(args: argparse.Namespace) -> int:
    try:
        store = EventStore(args.db)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        events = store.events(args.run_id)
    except KeyError:
        print(f"error: unknown run: {args.run_id}", file=sys.stderr)
        store.close()
        return 1

    for ev in events:
        record: dict[str, Any] = {
            "seq": ev.seq,
            "event_type": ev.event_type.value,
            "task_id": ev.task_id,
        }
        if ev.instruction_id:
            record["instruction_id"] = ev.instruction_id
        if ev.invocation_id:
            record["invocation_id"] = ev.invocation_id
        if ev.payload is not None:
            record["payload"] = ev.payload
        print(json.dumps(record, sort_keys=True, ensure_ascii=False))

    store.close()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tikhon",
        description="Executable text harness for durable AI thinking programs.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_lint = sub.add_parser("lint", help="Parse and validate a program")
    p_lint.add_argument("program", help="Path to .think source file")
    p_lint.set_defaults(func=_cmd_lint)

    p_seal = sub.add_parser("seal", help="Print the sealed sha256 digest")
    p_seal.add_argument("program", help="Path to .think source file")
    p_seal.set_defaults(func=_cmd_seal)

    p_run = sub.add_parser("run", help="Execute a sealed program")
    p_run.add_argument("program", help="Path to .think source file")
    p_run.add_argument("--db", required=True, help="Path to event store database")
    p_run.add_argument("--run-id", required=True, help="Unique run identifier")
    p_run.add_argument("--seal", default=None, help="Sealed digest required before run")
    p_run.set_defaults(func=_cmd_run)

    p_status = sub.add_parser("status", help="Print run status")
    p_status.add_argument("--db", required=True, help="Path to event store database")
    p_status.add_argument("--run-id", required=True, help="Run identifier")
    p_status.set_defaults(func=_cmd_status)

    p_events = sub.add_parser("events", help="Print ordered event log")
    p_events.add_argument("--db", required=True, help="Path to event store database")
    p_events.add_argument("--run-id", required=True, help="Run identifier")
    p_events.set_defaults(func=_cmd_events)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
