from __future__ import annotations

from ouro.capabilities.builder import AgentBuilder
from ouro.core.loop import EventSource, ProgressEvent, ScopedProgressSink


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    def emit(self, event: ProgressEvent) -> None:
        self.events.append(event)

    def spinner(self, label: str, title: str | None = None):
        raise AssertionError("spinner should not be used in this test")

    def on_session_loaded(self, messages):
        return None


def test_scoped_progress_sink_applies_default_source() -> None:
    recorder = _Recorder()
    sink = ScopedProgressSink(
        recorder,
        EventSource(
            agent_id="agent-1",
            parent_agent_id="root",
            root_agent_id="root",
            run_id="run-123",
            depth=1,
            role="worker",
        ),
    )

    sink.emit(ProgressEvent(kind="info", payload={"message": "hello"}))

    assert recorder.events == [
        ProgressEvent(
            kind="info",
            payload={"message": "hello"},
            source=EventSource(
                agent_id="agent-1",
                parent_agent_id="root",
                root_agent_id="root",
                run_id="run-123",
                depth=1,
                role="worker",
            ),
        )
    ]


def test_scoped_progress_sink_preserves_explicit_source() -> None:
    recorder = _Recorder()
    sink = ScopedProgressSink(recorder, EventSource(agent_id="agent-1"))

    sink.emit(
        ProgressEvent(
            kind="info",
            payload={"message": "hello"},
            source=EventSource(agent_id="override", role="verifier"),
        )
    )

    assert recorder.events == [
        ProgressEvent(
            kind="info",
            payload={"message": "hello"},
            source=EventSource(agent_id="override", role="verifier"),
        )
    ]


def test_worker_progress_identity_inherits_parent_lineage() -> None:
    parent = AgentBuilder().with_progress_identity(
        agent_id="root",
        root_agent_id="root",
        run_id="run-123",
        depth=0,
        role="root",
    )
    parent_identity = parent._progress_identity()
    assert parent_identity is not None

    worker = AgentBuilder().with_progress_identity(
        agent_id="agent-2",
        parent_agent_id=parent_identity.agent_id,
        root_agent_id=parent_identity.root_agent_id or parent_identity.agent_id,
        run_id=parent_identity.run_id,
        depth=parent_identity.depth + 1,
        role="worker",
    )

    worker_identity = worker._progress_identity()

    assert worker_identity is not None
    assert worker_identity.to_event_source() == EventSource(
        agent_id="agent-2",
        parent_agent_id="root",
        root_agent_id="root",
        run_id="run-123",
        depth=1,
        role="worker",
    )


def test_root_progress_identity_defaults_root_agent_id() -> None:
    builder = AgentBuilder().with_progress_identity(
        agent_id="root",
        run_id="run-123",
        role="root",
    )

    identity = builder._progress_identity()

    assert identity is not None
    assert identity.to_event_source() == EventSource(
        agent_id="root",
        root_agent_id="root",
        run_id="run-123",
        depth=0,
        role="root",
    )


def test_agent_builder_progress_identity_builds_expected_source() -> None:
    builder = AgentBuilder().with_progress_identity(
        agent_id="worker-2",
        parent_agent_id="root",
        root_agent_id="root",
        run_id="run-123",
        depth=1,
        role="worker",
    )

    identity = builder._progress_identity()

    assert identity is not None
    assert identity.to_event_source() == EventSource(
        agent_id="worker-2",
        parent_agent_id="root",
        root_agent_id="root",
        run_id="run-123",
        depth=1,
        role="worker",
    )
