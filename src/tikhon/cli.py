"""Command-line interface for tikhon (docs/spec/02-command-catalog.md).

Commands: lint, seal, run, resume, status, events, audit, learn, next,
submit, ready, claim.  Uses argparse and the standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from tikhon.audit import audit_run
from tikhon.bridge import ClaimBridge
from tikhon.envelope import (
    EnvelopeValidationError,
    ExternalDriver,
    ResultEnvelope,
)
from tikhon.learn import mine_run_directory
from tikhon.memory import KnowledgeBase
from tikhon.registry import builtin_registry
from tikhon.resume import resume_run
from tikhon.runtime import DeterministicWorker, EventStore, EventType, SequentialCoordinator
from tikhon.syntax import ParseError, parse_program, seal_digest, validate_program
from tikhon.worker_adapter import DEFAULT_TIMEOUT_SECONDS, ModelWorker


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

    # Issue #25: the deterministic delegate handler replies with a FIXED
    # canonical sample plan (so tests and CI never need a model).  The
    # plan declares G.goal/C.constraints INPUT placeholders; the
    # coordinator binds the delegate step's resolved arguments onto them
    # by leaf name before the child run starts, so the sample echoes the
    # committed goal without the handler knowing any run identity.
    def _delegate(**kwargs: Any) -> Any:
        goal = kwargs.get("goal")
        if not isinstance(goal, (str, dict, list)) or (
            isinstance(goal, str) and not goal.strip()
        ):
            raise ValueError(
                "delegate requires a nonempty committed goal argument"
            )
        return (
            "PROGRAM delegated_child VERSION 1.0\n"
            "\n"
            "INPUT\n"
            "    G.goal = \"\"\n"
            "    C.constraints = \"\"\n"
            "\n"
            "step.frame: DO define(request = G.goal) -> P.plan\n"
            "step.measure: DO calculate(expression = \"goal_units\","
            " values = {\"units\": 3}) -> F.metrics\n"
            "step.check: DO check(artifact = P.plan, predicate ="
            " \"nonempty\") -> V.verdict\n"
            "\n"
            "RETURN P.plan, F.metrics\n"
        )

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
        "delegate": _delegate,
    }


#: Commands whose handlers stay deterministic even under ``--worker model``
#: (issue #8): edit/test are sandboxed effectful operations a model cannot
#: perform, and review keeps the same deterministic result shape.
DETERMINISTIC_UNDER_MODEL = frozenset({"edit", "test", "review"})


class _HybridModelWorker:
    """Duck-type worker: ``edit``/``test``/``review`` stay deterministic.

    Wraps a ``ModelWorker`` (model routing for every other command) and a
    ``DeterministicWorker`` built from the standard handlers, dispatching
    the deterministic set to the handlers (issue #8 requirement 4).
    """

    def __init__(self, model_worker: Any, deterministic: DeterministicWorker):
        self._model_worker = model_worker
        self._deterministic = deterministic

    @property
    def commands(self) -> set[str]:
        return self._model_worker.commands | self._deterministic.commands

    def execute(self, command: str, resolved_kwargs: dict[str, Any]) -> Any:
        if command in DETERMINISTIC_UNDER_MODEL and command in self._deterministic.commands:
            return self._deterministic.execute(command, resolved_kwargs)
        return self._model_worker.execute(command, resolved_kwargs)


def _make_http_transport(api_base: str, api_key: str) -> Any:
    """Minimal stdlib OpenAI-compatible chat-completions transport."""

    def transport(model: str, prompt: str) -> str:
        url = api_base.rstrip("/") + "/chat/completions"
        payload = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]

    return transport


def _make_exec_transport(template: str) -> Any:
    """Transport running an argv template via subprocess with a timeout."""

    def transport(model: str, prompt: str) -> str:
        try:
            parsed = json.loads(template)
        except ValueError:
            parsed = None
        if isinstance(parsed, list) and all(isinstance(part, str) for part in parsed):
            argv_template = parsed
        else:
            argv_template = shlex.split(template)
        argv = [
            part.replace("{model}", model).replace("{prompt}", prompt)
            for part in argv_template
        ]
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"exec transport exited with {proc.returncode}:"
                f" {(proc.stderr or '')[-500:]}"
            )
        return proc.stdout

    return transport


def _build_model_worker() -> ModelWorker:
    """Build a ModelWorker from TIKHON_* environment configuration.

    Raises ``ValueError`` with a clear message when required environment
    is missing or malformed — the caller prints it and exits 1 before any
    run is created (same guard style as ``--seal``).
    """
    transport_kind = os.environ.get("TIKHON_WORKER_TRANSPORT")
    if transport_kind not in ("http", "exec"):
        raise ValueError(
            f"TIKHON_WORKER_TRANSPORT must be 'http' or 'exec',"
            f" got {transport_kind!r}"
        )

    tier_models: dict[str, str] = {}
    raw_tiers = os.environ.get("TIKHON_TIER_MODELS")
    if raw_tiers:
        try:
            parsed_tiers = json.loads(raw_tiers)
        except ValueError as exc:
            raise ValueError(f"TIKHON_TIER_MODELS is not valid JSON: {exc}") from exc
        if not isinstance(parsed_tiers, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in parsed_tiers.items()
        ):
            raise ValueError(
                "TIKHON_TIER_MODELS must be a JSON object mapping"
                " tier (T0..T3) to model name"
            )
        tier_models = parsed_tiers

    default_model = os.environ.get("TIKHON_MODEL")
    if not default_model and not tier_models:
        raise ValueError(
            "no model configured: set TIKHON_MODEL or TIKHON_TIER_MODELS"
        )

    if transport_kind == "http":
        api_base = os.environ.get("TIKHON_API_BASE")
        api_key = os.environ.get("TIKHON_API_KEY")
        if not api_base or not api_key:
            raise ValueError(
                "http transport requires TIKHON_API_BASE and TIKHON_API_KEY"
            )
        transport = _make_http_transport(api_base, api_key)
    else:
        template = os.environ.get("TIKHON_EXEC_COMMAND")
        if not template or not template.strip():
            raise ValueError(
                "exec transport requires TIKHON_EXEC_COMMAND"
                " (argv template with {model} and {prompt} placeholders)"
            )
        transport = _make_exec_transport(template)

    return ModelWorker(
        registry=builtin_registry(),
        transport=transport,
        tier_models=tier_models,
        default_model=default_model,
    )


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

    # Guard before any run state exists: a misconfigured model worker must
    # fail clearly without creating a run (same guard style as --seal).
    model_worker: ModelWorker | None = None
    if args.worker == "model":
        try:
            model_worker = _build_model_worker()
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
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

    deterministic = DeterministicWorker(
        _deterministic_handlers(
            memory=memory, run_id=args.run_id, workspace_root=workspace
        )
    )
    if model_worker is not None:
        worker = _HybridModelWorker(model_worker, deterministic)
    else:
        worker = deterministic
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


def _cmd_resume(args: argparse.Namespace) -> int:
    if not args.seal:
        print("error: --seal is required for resume", file=sys.stderr)
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

    # Guard before touching the store: same guard style as --seal (issue #8).
    model_worker: ModelWorker | None = None
    if args.worker == "model":
        try:
            model_worker = _build_model_worker()
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
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

    deterministic = DeterministicWorker(
        _deterministic_handlers(
            memory=memory, run_id=args.run_id, workspace_root=workspace
        )
    )
    if model_worker is not None:
        worker = _HybridModelWorker(model_worker, deterministic)
    else:
        worker = deterministic

    try:
        result = resume_run(
            store,
            worker,
            args.run_id,
            program,
            memory=memory,
            workspace_root=workspace,
        )
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


def _load_validated_program(program_path: str, seal: str | None) -> Any:
    """Parse, seal-verify and validate a program (run's guard style).

    Returns the parsed program or ``None`` after printing the error.
    """
    try:
        text = _load_source(program_path)
        program = parse_program(text)
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    if seal is not None:
        actual_digest = seal_digest(program)
        if seal != actual_digest:
            print(
                f"error: seal digest mismatch: expected {actual_digest},"
                f" got {seal}",
                file=sys.stderr,
            )
            return None
    try:
        validate_program(program, known_commands=_builtin_command_names())
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    return program


def _open_external_driver(args: argparse.Namespace, program: Any) -> Any:
    """Open the event store + KB and build the external driver (Wave 8).

    Returns ``(store, memory, driver)`` or ``(None, None, None)`` after
    printing the error.
    """
    try:
        store = EventStore(args.db)
    except Exception as exc:
        print(f"error: cannot open event store: {exc}", file=sys.stderr)
        return None, None, None
    memory = KnowledgeBase(
        os.path.join(os.path.dirname(os.path.abspath(args.db)), "kb.sqlite")
    )
    workspace = (
        os.path.abspath(args.workspace)
        if args.workspace
        else os.path.dirname(os.path.abspath(args.db))
    )
    driver = ExternalDriver(
        store,
        program,
        args.run_id,
        registry=builtin_registry(),
        memory=memory,
        workspace_root=workspace,
        seal_digest=args.seal,
    )
    return store, memory, driver


def _close_driver(store: Any, memory: Any) -> None:
    if store is not None:
        store.close()
    if memory is not None:
        memory.close()


def _cmd_next(args: argparse.Namespace) -> int:
    if not args.seal:
        print("error: --seal is required for next", file=sys.stderr)
        return 1
    program = _load_validated_program(args.program, args.seal)
    if program is None:
        return 1

    store, memory, driver = _open_external_driver(args, program)
    if driver is None:
        return 1
    try:
        envelope = driver.next_envelope()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        _close_driver(store, memory)
        return 1
    print(envelope.to_json())
    _close_driver(store, memory)
    return 0


def _cmd_ready(args: argparse.Namespace) -> int:
    # `ready` claims anonymously; `claim` carries --claimant (same body).
    if not args.seal:
        print("error: --seal is required for ready", file=sys.stderr)
        return 1
    program = _load_validated_program(args.program, args.seal)
    if program is None:
        return 1

    store, memory, driver = _open_external_driver(args, program)
    if driver is None:
        return 1
    bridge = ClaimBridge(driver, claim_timeout_seconds=args.claim_timeout)
    try:
        outcome = bridge.ready(claimant=getattr(args, "claimant", None))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        _close_driver(store, memory)
        return 1
    print(json.dumps(outcome, sort_keys=True, ensure_ascii=False))
    _close_driver(store, memory)
    return 0


def _cmd_claim(args: argparse.Namespace) -> int:
    return _cmd_ready(args)


def _cmd_submit(args: argparse.Namespace) -> int:
    try:
        with open(args.result_file, encoding="utf-8") as fh:
            result_text = fh.read()
    except OSError as exc:
        print(f"error: cannot read result file: {exc}", file=sys.stderr)
        return 1

    try:
        result = ResultEnvelope.from_json(result_text)
    except EnvelopeValidationError as exc:
        print(f"error: malformed result envelope: {exc}", file=sys.stderr)
        return 1

    program = None
    if args.program:
        program = _load_validated_program(args.program, args.seal)
        if program is None:
            return 1

    try:
        store = EventStore(args.db)
    except Exception as exc:
        print(f"error: cannot open event store: {exc}", file=sys.stderr)
        return 1
    driver = ExternalDriver(
        store, program, args.run_id, registry=builtin_registry()
    )
    try:
        if args.claim_token is not None:
            bridge = ClaimBridge(
                driver, claim_timeout_seconds=args.claim_timeout
            )
            outcome = bridge.submit(result, claim_token=args.claim_token)
        else:
            # Legacy Wave 8 path: no claim bookkeeping (coordinator-driven
            # or claim-less external runs keep working unchanged).
            outcome = driver.submit_result(result)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    print(json.dumps(outcome, sort_keys=True, ensure_ascii=False))
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
    p_run.add_argument(
        "--worker",
        choices=["deterministic", "model"],
        default="deterministic",
        help=(
            "Worker backend: deterministic handlers (default, CI baseline)"
            " or model routing via TIKHON_* environment configuration"
        ),
    )
    p_run.set_defaults(func=_cmd_run)

    p_resume = sub.add_parser(
        "resume",
        help="Resume an interrupted run after a crash",
    )
    p_resume.add_argument("--db", required=True, help="Path to event store database")
    p_resume.add_argument("--run-id", required=True, help="Run identifier")
    p_resume.add_argument(
        "--program", required=True, help="Path to the sealed .think source file"
    )
    p_resume.add_argument(
        "--seal", default=None, help="Sealed digest, verified exactly like run"
    )
    p_resume.add_argument(
        "--workspace",
        default=None,
        help=(
            "Workspace root for effectful commands like edit"
            " (default: the --db directory)"
        ),
    )
    p_resume.add_argument(
        "--worker",
        choices=["deterministic", "model"],
        default="deterministic",
        help=(
            "Worker backend: deterministic handlers (default, CI baseline)"
            " or model routing via TIKHON_* environment configuration"
        ),
    )
    p_resume.set_defaults(func=_cmd_resume)

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

    p_next = sub.add_parser(
        "next",
        help=(
            "Render the task envelope for the run's next ready invocation"
            " (external driver, issue #18)"
        ),
    )
    p_next.add_argument("--db", required=True, help="Path to event store database")
    p_next.add_argument("--run-id", required=True, help="Run identifier")
    p_next.add_argument(
        "--program", required=True, help="Path to the sealed .think source file"
    )
    p_next.add_argument(
        "--seal", default=None, help="Sealed digest, verified exactly like run"
    )
    p_next.add_argument(
        "--workspace",
        default=None,
        help=(
            "Workspace root for effectful commands like edit"
            " (default: the --db directory)"
        ),
    )
    p_next.set_defaults(func=_cmd_next)

    p_submit = sub.add_parser(
        "submit",
        help=(
            "Submit a result envelope for a dispatched invocation"
            " (external driver, issue #18)"
        ),
    )
    p_submit.add_argument("--db", required=True, help="Path to event store database")
    p_submit.add_argument("--run-id", required=True, help="Run identifier")
    p_submit.add_argument(
        "--invocation-id", required=True, help="Invocation identifier (inv-N)"
    )
    p_submit.add_argument(
        "--result-file",
        required=True,
        help="Path to the JSON file carrying the result envelope",
    )
    p_submit.add_argument(
        "--program",
        default=None,
        help=(
            "Optional path to the sealed .think source file; when given,"
            " the run's recorded program identity is verified"
        ),
    )
    p_submit.add_argument(
        "--seal",
        default=None,
        help="Sealed digest, verified when --program is given",
    )
    p_submit.add_argument(
        "--claim-token",
        default=None,
        help=(
            "Claim token from tikhon ready/claim; validates the"
            " invocation's open claim before committing (issue #19);"
            " omit for the claim-less Wave 8 path"
        ),
    )
    p_submit.add_argument(
        "--claim-timeout",
        type=float,
        default=900.0,
        help=(
            "Seconds before an unsubmitted claim is considered dead"
            " (default 900); only used with --claim-token"
        ),
    )
    p_submit.set_defaults(func=_cmd_submit)

    p_ready = sub.add_parser(
        "ready",
        help=(
            "Render and claim the next ready invocation as a"
            " TaskEnvelope + claim token for an external driver"
            " (issue #19)"
        ),
    )
    p_ready.add_argument("--db", required=True, help="Path to event store database")
    p_ready.add_argument("--run-id", required=True, help="Run identifier")
    p_ready.add_argument(
        "--program", required=True, help="Path to the sealed .think source file"
    )
    p_ready.add_argument(
        "--seal", default=None, help="Sealed digest, verified exactly like run"
    )
    p_ready.add_argument(
        "--workspace",
        default=None,
        help=(
            "Workspace root for effectful commands like edit"
            " (default: the --db directory)"
        ),
    )
    p_ready.add_argument(
        "--claim-timeout",
        type=float,
        default=900.0,
        help=(
            "Seconds before an unsubmitted claim is considered dead and"
            " re-issued with a fresh token (default 900)"
        ),
    )
    p_ready.set_defaults(func=_cmd_ready)

    p_claim = sub.add_parser(
        "claim",
        help=(
            "Like ready, but records the claimant name on the"
            " INVOCATION_CLAIMED event (issue #19)"
        ),
    )
    p_claim.add_argument("--db", required=True, help="Path to event store database")
    p_claim.add_argument("--run-id", required=True, help="Run identifier")
    p_claim.add_argument(
        "--program", required=True, help="Path to the sealed .think source file"
    )
    p_claim.add_argument(
        "--seal", default=None, help="Sealed digest, verified exactly like run"
    )
    p_claim.add_argument(
        "--workspace",
        default=None,
        help=(
            "Workspace root for effectful commands like edit"
            " (default: the --db directory)"
        ),
    )
    p_claim.add_argument(
        "--claim-timeout",
        type=float,
        default=900.0,
        help=(
            "Seconds before an unsubmitted claim is considered dead and"
            " re-issued with a fresh token (default 900)"
        ),
    )
    p_claim.add_argument(
        "--claimant",
        default=None,
        help="Name recorded for the claiming driver/agent",
    )
    p_claim.set_defaults(func=_cmd_claim)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
