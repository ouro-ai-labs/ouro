"""Tests for task graph tools."""

from __future__ import annotations

import json

import pytest

from agent.tasks import (
    TaskBlockedError,
    TaskDependencyFrozenError,
    TaskStore,
)
from tools.task_tools import (
    TaskCreateTool,
    TaskDumpMdTool,
    TaskFanoutTool,
    TaskGetManyTool,
    TaskGetTool,
    TaskListTool,
    TaskUpdateTool,
)


@pytest.mark.asyncio
async def test_task_create_list_get_and_availability_gates_on_dependencies():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tlist = TaskListTool(store)
    tget = TaskGetTool(store)

    created_a = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    a_id = created_a["task"]["id"]

    created_b = json.loads(
        await create.execute(content="Do B", activeForm="Doing B", blockedBy=[a_id])
    )
    b_id = created_b["task"]["id"]

    listed = json.loads(await tlist.execute())
    assert listed["available"] == [a_id]
    assert "debugTasksMd" in listed
    assert "tasksMd" in listed
    assert f"- [ ] {b_id}: Do B" in listed["tasksMd"]
    assert "blockedBy:" in listed["tasksMd"]

    got_b = json.loads(await tget.execute(id=b_id))
    assert got_b["task"]["blockedBy"] == [a_id]

    # Completing A should make B available.
    await update.execute(id=a_id, status="completed")
    listed2 = json.loads(await tlist.execute())
    assert b_id in listed2["available"]


@pytest.mark.asyncio
async def test_task_update_add_blocks_and_remove_blocks_mutates_reverse_edges():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)

    a = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    b = json.loads(await create.execute(content="Do B", activeForm="Doing B"))
    a_id = a["task"]["id"]
    b_id = b["task"]["id"]

    await update.execute(id=a_id, addBlocks=[b_id])
    got_b = json.loads(await tget.execute(id=b_id))
    assert a_id in got_b["task"]["blockedBy"]

    await update.execute(id=a_id, removeBlocks=[b_id])
    got_b2 = json.loads(await tget.execute(id=b_id))
    assert a_id not in got_b2["task"]["blockedBy"]


@pytest.mark.asyncio
async def test_task_update_add_and_remove_blocked_by_edits_dependencies():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)

    a = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    b = json.loads(await create.execute(content="Do B", activeForm="Doing B"))
    a_id = a["task"]["id"]
    b_id = b["task"]["id"]

    await update.execute(id=b_id, addBlockedBy=[a_id])
    got_b = json.loads(await tget.execute(id=b_id))
    assert got_b["task"]["blockedBy"] == [a_id]

    await update.execute(id=b_id, removeBlockedBy=[a_id])
    got_b2 = json.loads(await tget.execute(id=b_id))
    assert got_b2["task"]["blockedBy"] == []


@pytest.mark.asyncio
async def test_task_update_includes_single_update_debug_metadata():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)

    created = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    task_id = created["task"]["id"]

    result = json.loads(
        await update.execute(id=task_id, status="completed", detail="long detail content")
    )
    assert result["task"]["id"] == task_id
    assert result["updateDebug"]["id"] == task_id
    assert result["updateDebug"]["status"] == "completed"
    assert result["updateDebug"]["detailChars"] >= len("long detail content")
    assert result["updateDebug"]["detailDigest"]
    assert "long detail content" in result["updateDebug"]["detailPreview"]


@pytest.mark.asyncio
async def test_task_update_includes_batch_update_debug_metadata():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)

    a = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    b = json.loads(await create.execute(content="Do B", activeForm="Doing B"))
    a_id = a["task"]["id"]
    b_id = b["task"]["id"]

    result = json.loads(
        await update.execute(
            updates=[
                {"id": a_id, "status": "completed", "detail": "detail A"},
                {"id": b_id, "status": "completed", "detail": "detail B"},
            ]
        )
    )
    assert len(result["updateDebug"]) == 2
    debug_by_id = {d["id"]: d for d in result["updateDebug"]}
    assert set(debug_by_id.keys()) == {a_id, b_id}
    assert debug_by_id[a_id]["status"] == "completed"
    assert debug_by_id[b_id]["status"] == "completed"
    assert "detail A" in debug_by_id[a_id]["detailPreview"]
    assert "detail B" in debug_by_id[b_id]["detailPreview"]


@pytest.mark.asyncio
async def test_task_update_rejects_start_or_complete_when_blocked_by_incomplete_deps():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)

    a = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    a_id = a["task"]["id"]
    b = json.loads(await create.execute(content="Do B", activeForm="Doing B", blockedBy=[a_id]))
    b_id = b["task"]["id"]

    with pytest.raises(TaskBlockedError) as excinfo:
        await update.execute(id=b_id, status="in_progress")
    assert excinfo.value.missing_deps == [a_id]

    with pytest.raises(TaskBlockedError) as excinfo2:
        await update.execute(id=b_id, status="completed")
    assert excinfo2.value.missing_deps == [a_id]


@pytest.mark.asyncio
async def test_task_update_rejects_dependency_edits_for_non_pending_tasks():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)

    a = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    a_id = a["task"]["id"]
    b = json.loads(await create.execute(content="Do B", activeForm="Doing B", blockedBy=[a_id]))
    b_id = b["task"]["id"]

    await update.execute(id=a_id, status="completed")
    await update.execute(id=b_id, status="in_progress")

    with pytest.raises(TaskDependencyFrozenError):
        await update.execute(id=b_id, addBlockedBy=[a_id])

    with pytest.raises(TaskDependencyFrozenError):
        await update.execute(id=b_id, blockedBy=[a_id])


@pytest.mark.asyncio
async def test_task_update_allows_editing_dependencies_when_reopening_to_pending():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)

    a = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    a_id = a["task"]["id"]
    b = json.loads(await create.execute(content="Do B", activeForm="Doing B", blockedBy=[a_id]))
    b_id = b["task"]["id"]
    c = json.loads(await create.execute(content="Do C", activeForm="Doing C"))
    c_id = c["task"]["id"]

    await update.execute(id=a_id, status="completed")
    await update.execute(id=b_id, status="in_progress")

    await update.execute(id=b_id, status="pending", addBlockedBy=[c_id])
    got_b = json.loads(await tget.execute(id=b_id))
    assert set(got_b["task"]["blockedBy"]) == {a_id, c_id}


@pytest.mark.asyncio
async def test_task_dump_md_writes_tasks_md_and_optional_debug(tmp_path):
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    dump = TaskDumpMdTool(store)

    created_a = json.loads(await create.execute(content="Do A", activeForm="Doing A"))
    a_id = created_a["task"]["id"]
    created_b = json.loads(
        await create.execute(content="Do B", activeForm="Doing B", blockedBy=[a_id])
    )
    b_id = created_b["task"]["id"]

    await update.execute(id=a_id, status="completed")

    tasks_path = tmp_path / "tasks.md"
    result = json.loads(await dump.execute(path=str(tasks_path), includeDebug=True))
    assert result["ok"] is True
    assert result["taskCount"] == 2

    tasks_text = tasks_path.read_text(encoding="utf-8")
    assert f"- [x] {a_id}: Do A" in tasks_text
    assert f"- [ ] {b_id}: Do B" in tasks_text
    assert "blockedBy:" in tasks_text

    debug_path = tmp_path / "tasks.debug.md"
    debug_text = debug_path.read_text(encoding="utf-8")
    assert "# tasks.md (debug)" in debug_text


@pytest.mark.asyncio
async def test_task_fanout_creates_children_and_rewrites_join_dependencies():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    fanout = TaskFanoutTool(store)
    tget = TaskGetTool(store)

    upstream = json.loads(await create.execute(content="Upstream", activeForm="Upstreaming"))
    upstream_id = upstream["task"]["id"]
    await update.execute(id=upstream_id, status="completed")
    phase = json.loads(
        await create.execute(content="Phase", activeForm="Phasing", blockedBy=[upstream_id])
    )
    phase_id = phase["task"]["id"]
    join = json.loads(
        await create.execute(content="Join", activeForm="Joining", blockedBy=[phase_id])
    )
    join_id = join["task"]["id"]

    result = json.loads(
        await fanout.execute(
            phaseId=phase_id,
            joinId=join_id,
            children=[
                {"content": "Leaf 1", "activeForm": "Leafing 1"},
                {"content": "Leaf 2", "activeForm": "Leafing 2"},
                {"content": "Leaf 3", "activeForm": "Leafing 3"},
                {"content": "Leaf 4", "activeForm": "Leafing 4"},
                {"content": "Leaf 5", "activeForm": "Leafing 5"},
            ],
        )
    )

    assert result["ok"] is True
    child_ids = result["childIds"]
    assert len(child_ids) == 5
    assert result["adoptedChildIds"] == []

    got_join = json.loads(await tget.execute(id=join_id))
    assert phase_id not in got_join["task"]["blockedBy"]
    assert got_join["task"]["blockedBy"] == child_ids

    # If the phase has no output, TaskFanout treats it as a pure container:
    # - children inherit phase.blockedBy, but do not depend on phaseId
    # - the phase is auto-completed to avoid blocking status updates
    got_phase = json.loads(await tget.execute(id=phase_id))
    assert got_phase["task"]["status"] == "completed"

    # Children should inherit the upstream dep, but not depend on the phaseId.
    for cid in child_ids:
        got_child = json.loads(await tget.execute(id=cid))
        assert upstream_id in got_child["task"]["blockedBy"]
        assert phase_id not in got_child["task"]["blockedBy"]


@pytest.mark.asyncio
async def test_task_fanout_phase_with_output_is_a_gate_and_children_depend_on_it():
    store = TaskStore()
    create = TaskCreateTool(store)
    fanout = TaskFanoutTool(store)
    tget = TaskGetTool(store)

    upstream = json.loads(await create.execute(content="Upstream", activeForm="Upstreaming"))
    upstream_id = upstream["task"]["id"]
    phase = json.loads(
        await create.execute(
            content="Phase",
            activeForm="Phasing",
            blockedBy=[upstream_id],
            status="completed",
            detail="Resolved inputs: A, B, C",
        )
    )
    phase_id = phase["task"]["id"]
    join = json.loads(
        await create.execute(content="Join", activeForm="Joining", blockedBy=[phase_id])
    )
    join_id = join["task"]["id"]

    result = json.loads(
        await fanout.execute(
            phaseId=phase_id,
            joinId=join_id,
            children=[
                {"content": "Leaf 1", "activeForm": "Leafing 1"},
                {"content": "Leaf 2", "activeForm": "Leafing 2"},
            ],
        )
    )
    assert result["ok"] is True
    child_ids = result["childIds"]

    for cid in child_ids:
        got_child = json.loads(await tget.execute(id=cid))
        assert phase_id in got_child["task"]["blockedBy"]
        assert upstream_id in got_child["task"]["blockedBy"]


@pytest.mark.asyncio
async def test_task_fanout_reuses_existing_child_by_content_and_updates_join():
    store = TaskStore()
    create = TaskCreateTool(store)
    fanout = TaskFanoutTool(store)
    tget = TaskGetTool(store)

    phase = json.loads(await create.execute(content="Phase", activeForm="Phasing"))
    phase_id = phase["task"]["id"]
    join = json.loads(
        await create.execute(content="Join", activeForm="Joining", blockedBy=[phase_id])
    )
    join_id = join["task"]["id"]

    existing = json.loads(
        await create.execute(content="Leaf 1", activeForm="Leafing 1", blockedBy=[phase_id])
    )
    existing_id = existing["task"]["id"]

    result = json.loads(
        await fanout.execute(
            phaseId=phase_id,
            joinId=join_id,
            children=[
                {"content": "Leaf 1", "activeForm": "Leafing 1"},
                {"content": "Leaf 2", "activeForm": "Leafing 2"},
            ],
        )
    )

    assert result["ok"] is True
    assert existing_id in result["childIds"]
    assert existing_id in (result.get("reusedChildIds") or [])
    assert existing_id not in (result.get("adoptedChildIds") or [])

    got_join = json.loads(await tget.execute(id=join_id))
    assert phase_id not in got_join["task"]["blockedBy"]
    assert existing_id in got_join["task"]["blockedBy"]


@pytest.mark.asyncio
async def test_task_detail_is_stored_and_task_get_includes_it():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tlist = TaskListTool(store)
    tget = TaskGetTool(store)

    created = json.loads(await create.execute(content="Do X", activeForm="Doing X"))
    tid = created["task"]["id"]

    await update.execute(id=tid, detail="long result")

    listed = json.loads(await tlist.execute())
    t = [x for x in listed["tasks"] if x["id"] == tid][0]
    assert t["hasDetail"] is True
    assert t["detailChars"] == len("long result")
    assert "detail" not in t

    got = json.loads(await tget.execute(id=tid))
    assert got["task"]["detail"] == "long result"


@pytest.mark.asyncio
async def test_task_get_many_returns_multiple_tasks_with_details():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    get_many = TaskGetManyTool(store)

    a = json.loads(await create.execute(content="A", activeForm="A"))
    b = json.loads(await create.execute(content="B", activeForm="B"))
    await update.execute(id=a["task"]["id"], detail="detail a")
    await update.execute(id=b["task"]["id"], detail="detail b")

    got = json.loads(await get_many.execute(ids=[a["task"]["id"], b["task"]["id"]]))
    assert got["ok"] is True
    assert [t["id"] for t in got["tasks"]] == [a["task"]["id"], b["task"]["id"]]
    assert got["tasks"][0]["detail"] == "detail a"
    assert got["tasks"][1]["detail"] == "detail b"


@pytest.mark.asyncio
async def test_task_update_appends_detail_by_default_and_replace_detail_overwrites():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)

    created = json.loads(await create.execute(content="Do X", activeForm="Doing X"))
    tid = created["task"]["id"]

    await update.execute(id=tid, detail="first")
    await update.execute(id=tid, detail="second")
    got = json.loads(await tget.execute(id=tid))
    assert got["task"]["detail"] == "first\n\n---\n\nsecond"

    await update.execute(id=tid, detail="third", replaceDetail=True)
    got2 = json.loads(await tget.execute(id=tid))
    assert got2["task"]["detail"] == "third"

    # Empty detail does not clear by default (no-op).
    await update.execute(id=tid, detail="")
    got3 = json.loads(await tget.execute(id=tid))
    assert got3["task"]["detail"] == "third"


@pytest.mark.asyncio
async def test_task_update_append_only_keeps_existing_when_new_detail_is_subset():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)

    created = json.loads(await create.execute(content="Do X", activeForm="Doing X"))
    tid = created["task"]["id"]

    await update.execute(id=tid, detail="alpha beta gamma", replaceDetail=True)
    await update.execute(id=tid, detail="alpha")
    got = json.loads(await tget.execute(id=tid))
    assert got["task"]["detail"] == "alpha beta gamma"


@pytest.mark.asyncio
async def test_task_update_batch_append_only_keeps_existing_when_new_detail_is_subset():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)

    created = json.loads(await create.execute(content="Do X", activeForm="Doing X"))
    tid = created["task"]["id"]

    await update.execute(id=tid, detail="alpha beta gamma", replaceDetail=True)
    await update.execute(updates=[{"id": tid, "detail": "beta"}])
    got = json.loads(await tget.execute(id=tid))
    assert got["task"]["detail"] == "alpha beta gamma"


@pytest.mark.asyncio
async def test_task_update_supports_batch_updates_for_multiple_tasks():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tlist = TaskListTool(store)
    tget = TaskGetTool(store)

    a = json.loads(await create.execute(content="Identify", activeForm="Identifying"))
    a_id = a["task"]["id"]
    b = json.loads(await create.execute(content="Leaf B", activeForm="Leafing B", blockedBy=[a_id]))
    b_id = b["task"]["id"]
    c = json.loads(await create.execute(content="Leaf C", activeForm="Leafing C", blockedBy=[a_id]))
    c_id = c["task"]["id"]
    join = json.loads(
        await create.execute(content="Join", activeForm="Joining", blockedBy=[b_id, c_id])
    )
    join_id = join["task"]["id"]

    await update.execute(id=a_id, status="completed")
    listed = json.loads(await tlist.execute())
    assert set(listed["available"]) == {b_id, c_id}

    result = json.loads(
        await update.execute(
            updates=[
                {"id": b_id, "status": "completed", "detail": "result b", "replaceDetail": True},
                {"id": c_id, "status": "completed", "detail": "result c", "replaceDetail": True},
            ]
        )
    )
    assert "tasks" in result
    assert {t["id"] for t in result["tasks"]} == {b_id, c_id}

    got_b = json.loads(await tget.execute(id=b_id))
    got_c = json.loads(await tget.execute(id=c_id))
    assert got_b["task"]["detail"] == "result b"
    assert got_c["task"]["detail"] == "result c"

    listed2 = json.loads(await tlist.execute())
    assert join_id in listed2["available"]


@pytest.mark.asyncio
async def test_task_update_batch_rejects_duplicate_task_ids():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)

    t = json.loads(await create.execute(content="Do X", activeForm="Doing X"))
    tid = t["task"]["id"]

    with pytest.raises(ValueError, match="Duplicate id in updates"):
        await update.execute(
            updates=[
                {"id": tid, "detail": "a"},
                {"id": tid, "detail": "b"},
            ]
        )


@pytest.mark.asyncio
async def test_task_update_can_complete_using_stashed_detail_when_detail_omitted():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)
    tget = TaskGetTool(store)

    created = json.loads(await create.execute(content="Do X", activeForm="Doing X"))
    tid = created["task"]["id"]

    await store.stash_detail(tid, "stashed output")
    await update.execute(id=tid, status="completed")

    got = json.loads(await tget.execute(id=tid))
    assert got["task"]["status"] == "completed"
    assert got["task"]["detail"] == "stashed output"


@pytest.mark.asyncio
async def test_task_update_response_includes_detail_for_single_update():
    store = TaskStore()
    create = TaskCreateTool(store)
    update = TaskUpdateTool(store)

    created = json.loads(await create.execute(content="Do X", activeForm="Doing X"))
    tid = created["task"]["id"]

    resp = json.loads(await update.execute(id=tid, detail="long result", replaceDetail=True))
    assert resp["task"]["id"] == tid
    assert resp["task"]["detail"] == "long result"
