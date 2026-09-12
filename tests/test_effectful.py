"""End-to-end and security tests for effectful commands (issue #9).

Covers the real CLI handlers: ``edit`` writes under the workspace root and
refuses absolute paths and ``..`` escapes, ``test`` runs pytest in a
subprocess and returns ``{"exit_code", "tail"}``, ``review`` returns the
artifact refs.  Sealed programs drive ``atlas run`` with ``--workspace``
and must fail coherently (FAILED + RUN_FINISHED, no partial state) on
traversal attempts.  Every INVOCATION_DISPATCHED payload carries the
``<run_id>:<invocation_id>`` idempotency key.
"""

import json
import os

import pytest

from atlas.cli import _deterministic_handlers, main
from atlas.runtime import EventStore, EventType

PROGRAM = """\
PROGRAM effectful_demo VERSION 1.0

INPUT
  G.path = "scratch/test_demo.py"
  G.content = "def test_ok():\\n    assert 1 + 1 == 2\\n"

step.write: DO edit(path = G.path, content = G.content) -> E.written
step.test: DO test(path = E.written, timeout_seconds = 60) -> OUT.exit_code, OUT.tail
  DONE OUT.exit_code == 0
step.review: DO review(artifact_refs = [E.written], focus = "workspace hygiene") -> OUT.findings

RETURN E.written, OUT.exit_code, OUT.findings
"""

ABSOLUTE_PATH_PROGRAM = """\
PROGRAM absolute_edit VERSION 1.0

INPUT
  G.path = "/tmp/atlas-should-never-write-here.py"
  G.content = "malicious"

step.write: DO edit(path = G.path, content = G.content) -> E.written
RETURN E.written
"""

TRAVERSAL_PROGRAM = """\
PROGRAM traversal_edit VERSION 1.0

INPUT
  G.path = "../escaped.txt"
  G.content = "escape"

step.write: DO edit(path = G.path, content = G.content) -> E.written
step.echo: DO define(value = G.path) -> E.echo
RETURN E.written, E.echo
"""


def write_program(tmp_path, text, name="demo.think"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def run_cli(argv):
    from atlas.cli import main as cli_main

    rc = cli_main(argv)
    return rc


def seal_digest(program_path):
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = run_cli(["seal", str(program_path)])
    assert rc == 0
    return buffer.getvalue().strip()


def run_program(tmp_path, text, workspace=None, run_id="run-1", name="demo.think"):
    program_path = write_program(tmp_path, text, name=name)
    db = tmp_path / "events.db"
    digest = seal_digest(program_path)
    argv = [
        "run", str(program_path),
        "--db", str(db),
        "--run-id", run_id,
        "--seal", digest,
    ]
    if workspace is not None:
        argv += ["--workspace", str(workspace)]
    rc = run_cli(argv)
    return db, rc


def events_of(db, run_id):
    store = EventStore(db)
    try:
        return list(store.events(run_id))
    finally:
        store.close()


# --- end-to-end: edit then test then review succeeds --------------------------


def test_edit_then_test_then_review_run_succeeds(tmp_path):
    workspace = tmp_path / "ws"
    db, rc = run_program(tmp_path, PROGRAM, workspace=workspace)

    assert rc == 0
    edited = workspace / "scratch" / "test_demo.py"
    assert edited.is_file()
    assert edited.read_text(encoding="utf-8") == "def test_ok():\n    assert 1 + 1 == 2\n"

    events = events_of(db, "run-1")
    assert events[-1].event_type is EventType.RUN_FINISHED
    assert events[-1].payload["status"] == "succeeded"

    state_store = EventStore(db)
    try:
        state = state_store.project_state("run-1")
    finally:
        state_store.close()
    assert state["nodes"]["E.written"]["value"] == "scratch/test_demo.py"
    assert state["nodes"]["OUT.exit_code"]["value"] == 0
    assert state["nodes"]["OUT.findings"]["value"] == ["scratch/test_demo.py"]

    dispatched = [
        event for event in events
        if event.event_type is EventType.INVOCATION_DISPATCHED
    ]
    assert [event.payload["idempotency_key"] for event in dispatched] == [
        "run-1:inv-1", "run-1:inv-2", "run-1:inv-3",
    ]


def test_run_without_workspace_defaults_to_the_db_directory(tmp_path):
    db, rc = run_program(tmp_path, PROGRAM, workspace=None)

    assert rc == 0
    assert (tmp_path / "scratch" / "test_demo.py").is_file()
    events = events_of(db, "run-1")
    assert events[-1].payload["status"] == "succeeded"


# --- end-to-end: traversal attempts fail coherently ---------------------------


@pytest.mark.parametrize(
    "program",
    [ABSOLUTE_PATH_PROGRAM, TRAVERSAL_PROGRAM],
    ids=["absolute-path", "dotdot-escape"],
)
def test_edit_traversal_fails_the_run_coherently(tmp_path, program):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    db, rc = run_program(tmp_path, program, workspace=workspace)

    assert rc == 2
    events = events_of(db, "run-1")
    assert events[-1].event_type is EventType.RUN_FINISHED
    assert events[-1].payload["status"] == "failed"
    failed = [
        event for event in events if event.event_type is EventType.FAILED
    ]
    assert len(failed) == 1
    assert failed[0].invocation_id == "inv-1"
    assert "workspace" in failed[0].payload["error"]

    # no partial state: nothing written inside or outside the workspace
    assert list(workspace.iterdir()) == []
    assert not (tmp_path / "escaped.txt").exists()
    assert not os.path.exists("/tmp/atlas-should-never-write-here.py")

    state_store = EventStore(db)
    try:
        state = state_store.project_state("run-1")
        profile = state_store.task_ledger("run-1").profile()
    finally:
        state_store.close()
    assert set(state["nodes"]) == set()
    assert profile["counts"]["cancelled"] == profile["counts"]["total"]


def test_traversal_failure_cancels_following_steps(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    db, rc = run_program(
        tmp_path, TRAVERSAL_PROGRAM, workspace=workspace, run_id="run-esc"
    )

    assert rc == 2
    events = events_of(db, "run-esc")
    assert not (tmp_path / "escaped.txt").exists()
    echo_events = [
        event for event in events if event.invocation_id == "inv-2"
    ]
    assert echo_events == []
    cancelled = [
        event for event in events
        if event.event_type is EventType.TASK_UPDATED
        and event.payload.get("kind") == "task_cancelled"
    ]
    assert len(cancelled) == 2


# --- handler-level security: path traversal rejected --------------------------


@pytest.fixture
def handlers(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return _deterministic_handlers(workspace_root=str(workspace)), workspace


@pytest.mark.parametrize(
    "bad_path",
    [
        "/etc/passwd",
        "/tmp/abs.txt",
        "../outside.txt",
        "a/../../outside.txt",
        "..",
        "scratch/../../outside.txt",
    ],
)
def test_edit_handler_rejects_traversal_paths(handlers, bad_path):
    handlers_dict, workspace = handlers
    with pytest.raises(ValueError, match="workspace"):
        handlers_dict["edit"](path=bad_path, content="payload")
    assert list(workspace.rglob("*")) == []


def test_edit_handler_rejects_malformed_inputs(handlers):
    handlers_dict, workspace = handlers
    with pytest.raises(ValueError):
        handlers_dict["edit"](path="", content="x")
    with pytest.raises(ValueError):
        handlers_dict["edit"](path="ok.txt", content=None)
    with pytest.raises(ValueError):
        handlers_dict["edit"](path=None, content="x")
    assert list(workspace.rglob("*")) == []


def test_edit_handler_requires_a_workspace_root():
    bare = _deterministic_handlers()
    with pytest.raises(ValueError, match="workspace"):
        bare["edit"](path="ok.txt", content="x")


def test_edit_handler_writes_relative_file_and_returns_relative_path(handlers):
    handlers_dict, workspace = handlers
    result = handlers_dict["edit"](path="sub/dir/file.txt", content="hello")
    assert result == os.path.join("sub", "dir", "file.txt")
    assert (workspace / "sub" / "dir" / "file.txt").read_text(encoding="utf-8") == "hello"


def test_edit_handler_overwrites_existing_file_idempotently(handlers):
    handlers_dict, workspace = handlers
    first = handlers_dict["edit"](path="file.txt", content="v1")
    second = handlers_dict["edit"](path="file.txt", content="v2")
    assert first == second == "file.txt"
    assert (workspace / "file.txt").read_text(encoding="utf-8") == "v2"


def test_test_handler_runs_pytest_and_returns_exit_code_and_tail(handlers):
    handlers_dict, workspace = handlers
    handlers_dict["edit"](
        path="test_ok.py", content="def test_ok():\n    assert True\n"
    )
    result = handlers_dict["test"](path="test_ok.py", timeout_seconds=60)
    assert set(result) == {"exit_code", "tail"}
    assert result["exit_code"] == 0
    assert "passed" in result["tail"]


def test_test_handler_reports_failing_suite_exit_code(handlers):
    handlers_dict, _workspace = handlers
    handlers_dict["edit"](
        path="test_bad.py", content="def test_bad():\n    assert False\n"
    )
    result = handlers_dict["test"](path="test_bad.py", timeout_seconds=60)
    assert result["exit_code"] == 1
    assert "failed" in result["tail"]


def test_test_handler_bounds_the_tail_to_40_lines(handlers):
    handlers_dict, workspace = handlers
    noisy = "def test_noisy():\n" + "".join(
        f"    print('line {i}')\n" for i in range(80)
    ) + "    assert True\n"
    handlers_dict["edit"](path="test_noisy.py", content=noisy)
    result = handlers_dict["test"](path="test_noisy.py", timeout_seconds=60)
    assert len(result["tail"].splitlines()) <= 40


@pytest.mark.parametrize("bad_path", ["../outside", "/abs/path"])
def test_test_handler_rejects_traversal_paths(handlers, bad_path):
    handlers_dict, _workspace = handlers
    with pytest.raises(ValueError, match="workspace"):
        handlers_dict["test"](path=bad_path, timeout_seconds=5)


def test_review_handler_returns_the_artifact_refs():
    bare = _deterministic_handlers()
    refs = ["E.patch", "E.tests"]
    assert bare["review"](artifact_refs=refs, focus="hygiene") == refs


# --- dispatch payload records the idempotency key through the CLI -------------


def test_cli_dispatched_events_carry_idempotency_keys(tmp_path):
    workspace = tmp_path / "ws"
    db, rc = run_program(tmp_path, PROGRAM, workspace=workspace, run_id="run-keys")

    assert rc == 0
    events = events_of(db, "run-keys")
    dispatched = [
        event for event in events
        if event.event_type is EventType.INVOCATION_DISPATCHED
    ]
    assert len(dispatched) == 3
    for event in dispatched:
        assert event.payload["idempotency_key"] == (
            f"run-keys:{event.invocation_id}"
        )
    # only the effectful edit dispatch learns the workspace root
    assert dispatched[0].payload["args"]["_workspace_root"] == str(workspace)
    assert "_workspace_root" not in dispatched[1].payload["args"]
    assert "_workspace_root" not in dispatched[2].payload["args"]
