"""Command-line interface for tikhon (docs/spec/02-command-catalog.md).

Commands: lint, seal, run, status, events, audit, learn.
Uses argparse and the standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from tikhon.audit import audit_run
from tikhon.learn import mine_run_directory
from tikhon.memory import KnowledgeBase
from tikhon.registry import builtin_registry
from tikhon.runtime import DeterministicWorker, EventStore, EventType, SequentialCoordinator
from tikhon.syntax import ParseError, parse_program, seal_digest, validate_program


def _load_source(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _builtin_command_names() -> set[str]:
    return set(builtin_registry().names())


def _resolve_workspace_path(
    root: str, path: Any, *, what: str
) -> str:
    """Resolve ``path`` under workspace ``root``, refusing escapes.

    Rejects non-string, empty, absolute, and ``..``-traversal paths with a
    ``ValueError`` naming the defect (issue #9 security rule).  Returns the
    absolute, symlink-resolved candidate path.
    """
    if not isinstance(path, str) or not path.strip():
        raise ValueError(f"{what} requires a nonempty string path, got {path!r}")
    if os.path.isabs(path):
        raise ValueError(
            f"{what} refuses absolute paths: {path!r} is not relative"
            " to the workspace root"
        )
    normalized = os.path.normpath(path)
    if normalized == "." or normalized.startswith(".." + os.sep) or normalized == "..":
        raise ValueError(
            f"{what} refuses path traversal outside the workspace root: {path!r}"
        )
    root_real = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(root_real, normalized))
    if candidate != root_real and not candidate.startswith(root_real + os.sep):
        raise ValueError(
            f"{what} refuses path traversal outside the workspace root: {path!r}"
        )
    return candidate


def _deterministic_handlers(
    memory: Any = None, run_id: str = "", workspace_root: str | None = None
) -> dict[str, Any]:
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

    def _require_memory() -> Any:
        if memory is None:
            raise ValueError(
                "remember/recall require a knowledge base: the run must be"
                " wired with KnowledgeBase(<db dir>/kb.sqlite)"
            )
        return memory

    def _remember(**kwargs: Any) -> Any:
        kb = _require_memory()
        if "key" not in kwargs or "value" not in kwargs:
            raise ValueError("remember requires key and value arguments")
        return kb.set(kwargs["key"], kwargs["value"], source_run=run_id)

    def _recall(**kwargs: Any) -> Any:
        kb = _require_memory()
        query = kwargs.get("query")
        if not isinstance(query, str) or not query:
            raise ValueError("recall requires a kb. key or prefix query")
        if query in kb:
            return {query: kb.get(query)}
        return {key: kb.get(key) for key in kb.keys(prefix=query)}

    def _workspace_for(**kwargs: Any) -> str:
        root = kwargs.get("_workspace_root") or workspace_root
        if not isinstance(root, str) or not root:
            raise ValueError(
                "edit/test require a workspace root: pass --workspace to"
                " tikhon run (default: the --db directory)"
            )
        return root

    def _edit(**kwargs: Any) -> Any:
        root = _workspace_for(**kwargs)
        path = kwargs.get("path")
        content = kwargs.get("content")
        if not isinstance(content, str):
            raise ValueError(
                f"edit requires string content, got {type(content).__name__}"
            )
        target = _resolve_workspace_path(root, path, what="edit")
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        return os.path.relpath(target, os.path.realpath(root))

    def _test(**kwargs: Any) -> Any:
        import subprocess

        root = _workspace_for(**kwargs)
        target = _resolve_workspace_path(root, kwargs.get("path"), what="test")
        timeout = kwargs.get("timeout_seconds", 120)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError(
                f"test requires a positive timeout_seconds, got {timeout!r}"
            )
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", target],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                f"test exceeded its {timeout}s deadline on {kwargs.get('path')!r}"
            ) from exc
        output = (proc.stdout or "") + (proc.stderr or "")
        tail = "\n".join(output.splitlines()[-40:])
        return {"exit_code": proc.returncode, "tail": tail}

    def _review(**kwargs: Any) -> Any:
        return kwargs.get("artifact_refs", dict(kwargs))

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
        "remember": _remember,
        "recall": _recall,
        "edit": _edit,
        "test": _test,
        "review": _review,
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

    memory = KnowledgeBase(
        os.path.join(os.path.dirname(os.path.abspath(args.db)), "kb.sqlite")
    )

    workspace = (
        os.path.abspath(args.workspace)
        if args.workspace
        else os.path.dirname(os.path.abspath(args.db))
    )

    worker = DeterministicWorker(
        _deterministic_handlers(
            memory=memory, run_id=args.run_id, workspace_root=workspace
        )
    )
    coordinator = SequentialCoordinator(
        store, worker, memory=memory, workspace_root=workspace
    )

    try:
        result = coordinator.execute(program, run_id=args.run_id)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        store.close()
        memory.close()
        return 1
    finally:
        store.close()
        memory.close()

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


def _cmd_audit(args: argparse.Namespace) -> int:
    try:
        store = EventStore(args.db)
    except Exception as exc:
        print(f"error: cannot open event store: {exc}", file=sys.stderr)
        return 1

    try:
        report = audit_run(store, args.run_id)
    except KeyError:
        print(f"error: unknown run: {args.run_id}", file=sys.stderr)
        store.close()
        return 1
    except Exception as exc:
        print(f"error: audit failed: {exc}", file=sys.stderr)
        store.close()
        return 1
    store.close()

    if report.ok:
        print("OK")
        return 0

    print(f"violations: {len(report.findings)}")
    for finding in report.findings:
        seqs = ", ".join(str(seq) for seq in finding.seqs)
        print(f"- {finding.code} (seq: {seqs}): {finding.message}")
    return 1


def _cmd_learn(args: argparse.Namespace) -> int:
    try:
        report = mine_run_directory(Path(args.runs))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    markdown = report.to_markdown()
    print(markdown)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(markdown)
        print(args.out)
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
    p_run.add_argument(
        "--workspace",
        default=None,
        help=(
            "Workspace root for effectful commands like edit"
            " (default: the --db directory)"
        ),
    )
    p_run.set_defaults(func=_cmd_run)

    p_status = sub.add_parser("status", help="Print run status")
    p_status.add_argument("--db", required=True, help="Path to event store database")
    p_status.add_argument("--run-id", required=True, help="Run identifier")
    p_status.set_defaults(func=_cmd_status)

    p_events = sub.add_parser("events", help="Print ordered event log")
    p_events.add_argument("--db", required=True, help="Path to event store database")
    p_events.add_argument("--run-id", required=True, help="Run identifier")
    p_events.set_defaults(func=_cmd_events)

    p_audit = sub.add_parser(
        "audit", help="Verify a persisted run against audit invariants"
    )
    p_audit.add_argument("--db", required=True, help="Path to event store database")
    p_audit.add_argument("--run-id", required=True, help="Run identifier")
    p_audit.set_defaults(func=_cmd_audit)

    p_learn = sub.add_parser(
        "learn",
        help="Mine a runs directory into protocol candidates and failure clusters",
    )
    p_learn.add_argument(
        "--runs", required=True, help="Path to the runs directory to mine"
    )
    p_learn.add_argument(
        "--out", default=None, help="Optional path to write the markdown report"
    )
    p_learn.set_defaults(func=_cmd_learn)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
