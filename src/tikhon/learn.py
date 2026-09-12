"""tikhon learn — mine run directories into protocol candidates and failure clusters.

Wake-sleep companion (issue #13): "wake" is agents running programs in
``demo/runs/*``; "sleep" is this module compressing that experience into
language.  The output is a review-only :class:`LearnReport` — promotion to
``protocols/`` or the registry happens via human-approved PR only, and the
miner itself never writes anything (the CLI adds only the optional ``--out``
file).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tikhon.runtime.events import EventStore, EventType
from tikhon.syntax import ParseError, parse_program

__all__ = [
    "FailureCluster",
    "LearnReport",
    "ProtocolCandidate",
    "mine_run_directory",
]

# Minimum number of distinct programs a command sequence must appear in to
# become a protocol candidate.
MIN_SUPPORT = 2

# Failure quotes are truncated for readability in the report.
QUOTE_LIMIT = 200

# Maximum number of representative quotes shown per failure cluster.
REPRESENTATIVES = 3

# Normalized keyword buckets for failure clustering, in priority order: the
# first bucket whose keywords appear in the lowercased quote wins.  "other"
# matches everything and is the fallback.
_BUCKET_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "missing_commands",
        (
            "unknown command",
            "unregistered command",
            "missing command",
            "command not",
            "not registered",
            "no edit or test command",
            "command catalog",
            "registered command",
        ),
    ),
    (
        "reference_arrays",
        (
            "reference list",
            "ref list",
            "reference array",
            "ref array",
            "refs list",
            "list of refs",
            "list of references",
            "bracket",
            "comma-separated",
        ),
    ),
    (
        "identifier_syntax",
        (
            "identifier",
            "syntax",
            "parse",
            "malformed",
            "naming",
            "invalid ref",
            "unknown ref",
            "regex",
        ),
    ),
    (
        "path_errors",
        (
            "path",
            "traversal",
            "directory",
            "file not found",
            "filenotfound",
            "workspace root",
        ),
    ),
    ("other", ()),
)


@dataclass(frozen=True)
class ProtocolCandidate:
    """A recurring maximal step-command subsequence across programs."""

    commands: tuple[str, ...]
    support: int
    example_run_ids: tuple[str, ...]
    suggested_name: str


@dataclass(frozen=True)
class FailureCluster:
    """A normalized keyword bucket of failure/deviation quotes."""

    bucket: str
    count: int
    quotes: tuple[str, ...]
    run_ids: tuple[str, ...]


@dataclass(frozen=True)
class LearnReport:
    """Deterministic, review-only digest of a mined runs directory."""

    runs_dir: str
    run_ids: tuple[str, ...]
    candidates: tuple[ProtocolCandidate, ...]
    clusters: tuple[FailureCluster, ...]
    terminal_status_counts: dict[str, int]
    steps_planned_total: int
    steps_executed_total: int
    parse_error_runs: tuple[str, ...]
    call_skipped_runs: tuple[str, ...]
    worklogs_present: int
    event_stores_found: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict form of the report (issue #48)."""
        return {
            "runs_dir": self.runs_dir,
            "run_ids": list(self.run_ids),
            "candidates": [
                {
                    "commands": list(c.commands),
                    "support": c.support,
                    "example_run_ids": list(c.example_run_ids),
                    "suggested_name": c.suggested_name,
                }
                for c in self.candidates
            ],
            "clusters": [
                {
                    "bucket": c.bucket,
                    "count": c.count,
                    "quotes": list(c.quotes),
                    "run_ids": list(c.run_ids),
                }
                for c in self.clusters
            ],
            "terminal_status_counts": dict(self.terminal_status_counts),
            "steps_planned_total": self.steps_planned_total,
            "steps_executed_total": self.steps_executed_total,
            "parse_error_runs": list(self.parse_error_runs),
            "call_skipped_runs": list(self.call_skipped_runs),
            "worklogs_present": self.worklogs_present,
            "event_stores_found": self.event_stores_found,
        }

    def to_markdown(self) -> str:
        """Render a human-readable, deterministic review report."""
        lines: list[str] = []
        lines.append("# tikhon learn — mined run report")
        lines.append("")
        lines.append(f"Source: {self.runs_dir}")
        lines.append(f"Runs scanned: {len(self.run_ids)}")
        lines.append("")
        lines.append("## Routing telemetry")
        lines.append("")
        statuses = ", ".join(
            f"{status}={count}"
            for status, count in sorted(self.terminal_status_counts.items())
        )
        lines.append(f"- terminal statuses: {statuses or '(none)'}")
        lines.append(f"- steps planned (from programs): {self.steps_planned_total}")
        lines.append(
            f"- steps executed (from evaluation.json): {self.steps_executed_total}"
        )
        lines.append(
            "- programs with parse errors: "
            f"{len(self.parse_error_runs)}"
            f"{'' if not self.parse_error_runs else ' (' + ', '.join(self.parse_error_runs) + ')'}"
        )
        lines.append(
            "- programs skipped for CALL nesting: "
            f"{len(self.call_skipped_runs)}"
            f"{'' if not self.call_skipped_runs else ' (' + ', '.join(self.call_skipped_runs) + ')'}"
        )
        lines.append(f"- worklogs present: {self.worklogs_present}")
        lines.append(f"- event stores found: {self.event_stores_found}")
        lines.append("")
        lines.append(f"## Protocol candidates ({len(self.candidates)})")
        lines.append("")
        if not self.candidates:
            lines.append("(none)")
        else:
            for index, candidate in enumerate(self.candidates, start=1):
                lines.append(
                    f"{index}. {' -> '.join(candidate.commands)}"
                )
                lines.append(
                    f"   suggested protocol name: {candidate.suggested_name}"
                )
                lines.append(f"   support: {candidate.support} programs")
                lines.append(
                    "   runs: " + ", ".join(candidate.example_run_ids)
                )
        lines.append("")
        lines.append(f"## Failure clusters ({len(self.clusters)})")
        lines.append("")
        if not self.clusters:
            lines.append("(none)")
        else:
            for cluster in self.clusters:
                lines.append(
                    f"- {cluster.bucket}: {cluster.count} quote(s)"
                )
                for quote in cluster.quotes:
                    lines.append(f'  - "{quote}"')
                lines.append(
                    "  - runs: " + ", ".join(cluster.run_ids)
                )
        lines.append("")
        lines.append(
            "Promotion to protocols/ or the registry requires a human-approved"
            " PR; this report never writes there."
        )
        return "\n".join(lines)


def _bucket_for(quote: str) -> str:
    lowered = quote.lower()
    for bucket, keywords in _BUCKET_KEYWORDS:
        if not keywords or any(keyword in lowered for keyword in keywords):
            return bucket
    return "other"


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _quote_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        if value is None:
            return []
        return [_stringify(value)]
    return [_stringify(item) for item in value if _stringify(item).strip()]


def _failed_quotes(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        for key in ("error", "message", "detail", "reason"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return [value]
        return [_stringify(payload)]
    if isinstance(payload, str):
        return [payload] if payload.strip() else []
    return [_stringify(payload)]


def _event_store_quotes(run_dir: Path, run_ids: list[str]) -> tuple[int, list[str]]:
    """Read FAILED payloads from optional ``*.db`` event stores in ``run_dir``.

    Returns how many ``.db`` files were found and the quotes extracted.
    Every failure (missing tables, unknown run, corrupt store) is tolerated
    by yielding no quotes for that store.
    """
    quotes: list[str] = []
    found = 0
    for db_path in sorted(run_dir.glob("*.db")):
        found += 1
        for run_id in run_ids:
            try:
                store = EventStore(str(db_path))
            except Exception:
                break
            try:
                store.run(run_id)
                events = store.events(run_id)
            except Exception:
                store.close()
                continue
            try:
                for event in events:
                    if event.event_type is EventType.FAILED:
                        quotes.extend(_failed_quotes(event.payload))
            finally:
                store.close()
    return found, quotes


def _suggested_name(commands: tuple[str, ...]) -> str:
    prefix = "_".join(commands[:3])
    return f"{prefix}_pipeline"


def _is_contained(outer: tuple[str, ...], inner: tuple[str, ...]) -> bool:
    if len(inner) > len(outer):
        return False
    return any(
        outer[i : i + len(inner)] == inner
        for i in range(len(outer) - len(inner) + 1)
    )


def _mine_candidates(
    sequences: dict[str, list[str]],
) -> list[ProtocolCandidate]:
    """Find recurring maximal contiguous command sequences across programs.

    A candidate is a contiguous subsequence of one program's DO-command
    sequence (source order) that appears in at least ``MIN_SUPPORT`` distinct
    programs.  A candidate is maximal when no other candidate with equal or
    higher support contains it, so trivial prefixes/suffixes of an already
    reported pipeline are not double-counted.
    """
    grams: dict[tuple[str, ...], set[str]] = {}
    for run_id, commands in sequences.items():
        for width in range(2, len(commands) + 1):
            for start in range(len(commands) - width + 1):
                gram = tuple(commands[start : start + width])
                grams.setdefault(gram, set()).add(run_id)
    recurring = {
        gram: run_ids
        for gram, run_ids in grams.items()
        if len(run_ids) >= MIN_SUPPORT
    }
    candidates: list[ProtocolCandidate] = []
    for gram, run_ids in sorted(recurring.items()):
        dominated = any(
            other != gram
            and len(recurring[other]) >= len(run_ids)
            and _is_contained(other, gram)
            for other in recurring
        )
        if dominated:
            continue
        candidates.append(
            ProtocolCandidate(
                commands=gram,
                support=len(run_ids),
                example_run_ids=tuple(sorted(run_ids)),
                suggested_name=_suggested_name(gram),
            )
        )
    candidates.sort(key=lambda c: (-c.support, -len(c.commands), c.commands))
    return candidates


def _mine_clusters(quotes: dict[str, list[str]]) -> list[FailureCluster]:
    grouped: dict[str, list[tuple[str, str]]] = {}
    for run_id in sorted(quotes):
        for quote in quotes[run_id]:
            grouped.setdefault(_bucket_for(quote), []).append((run_id, quote))
    clusters: list[FailureCluster] = []
    for bucket, _keywords in _BUCKET_KEYWORDS:
        entries = grouped.get(bucket)
        if not entries:
            continue
        truncated = sorted({quote[:QUOTE_LIMIT] for _run, quote in entries})
        clusters.append(
            FailureCluster(
                bucket=bucket,
                count=len(entries),
                quotes=tuple(truncated[:REPRESENTATIVES]),
                run_ids=tuple(sorted({run for run, _quote in entries})),
            )
        )
    return clusters


def mine_run_directory(runs_dir: Path) -> LearnReport:
    """Scan ``runs_dir/*/`` run artifacts into a deterministic report.

    Reads, per run directory: ``program.think`` (parse failures tolerated),
    ``evaluation.json`` (missing/invalid tolerated), ``WORKLOG.md``
    (optional), and any ``*.db`` event store sitting next to them
    (optional; read failures tolerated).  Raises ``FileNotFoundError`` if
    ``runs_dir`` is not a readable directory.  Never writes anything.
    """
    runs_path = Path(runs_dir)
    if not runs_path.is_dir():
        raise FileNotFoundError(f"runs directory not found: {runs_path}")

    run_ids: list[str] = []
    sequences: dict[str, list[str]] = {}
    statuses: Counter[str] = Counter()
    steps_planned_total = 0
    steps_executed_total = 0
    parse_error_runs: list[str] = []
    call_skipped_runs: list[str] = []
    worklogs_present = 0
    event_stores_found = 0
    failure_quotes: dict[str, list[str]] = {}

    for run_dir in sorted(p for p in runs_path.iterdir() if p.is_dir()):
        run_id = run_dir.name
        run_ids.append(run_id)

        commands: list[str] = []
        planned = 0
        program_path = run_dir / "program.think"
        if program_path.is_file():
            try:
                program = parse_program(program_path.read_text(encoding="utf-8"))
            except (ParseError, OSError, UnicodeDecodeError):
                parse_error_runs.append(run_id)
            else:
                for statement in program.statements:
                    if statement.__class__.__name__ == "Invocation":
                        commands.append(statement.command)
                        planned += 1
                    elif statement.__class__.__name__ == "Call":
                        planned += 1
                if any(
                    statement.__class__.__name__ == "Call"
                    for statement in program.statements
                ):
                    call_skipped_runs.append(run_id)
                else:
                    sequences[run_id] = commands

        evaluation: dict[str, Any] = {}
        evaluation_path = run_dir / "evaluation.json"
        if evaluation_path.is_file():
            try:
                loaded = json.loads(
                    evaluation_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError, UnicodeDecodeError):
                loaded = None
            if isinstance(loaded, dict):
                evaluation = loaded
        status = evaluation.get("terminal_status")
        statuses[str(status) if status is not None else "unknown"] += 1
        executed = evaluation.get("steps_executed")
        if isinstance(executed, int):
            steps_executed_total += executed
        steps_planned_total += planned

        if (run_dir / "WORKLOG.md").is_file():
            worklogs_present += 1

        run_failure_quotes: list[str] = []
        for key in ("protocol_deviations", "unresolved"):
            run_failure_quotes.extend(_quote_list(evaluation.get(key)))
        store_count, store_quotes = _event_store_quotes(
            run_dir, [run_id, str(evaluation.get("run_id", ""))]
        )
        event_stores_found += store_count
        run_failure_quotes.extend(store_quotes)
        if run_failure_quotes:
            failure_quotes[run_id] = run_failure_quotes

    return LearnReport(
        runs_dir=str(runs_path),
        run_ids=tuple(run_ids),
        candidates=tuple(_mine_candidates(sequences)),
        clusters=tuple(_mine_clusters(failure_quotes)),
        terminal_status_counts=dict(statuses),
        steps_planned_total=steps_planned_total,
        steps_executed_total=steps_executed_total,
        parse_error_runs=tuple(sorted(parse_error_runs)),
        call_skipped_runs=tuple(sorted(call_skipped_runs)),
        worklogs_present=worklogs_present,
        event_stores_found=event_stores_found,
    )
