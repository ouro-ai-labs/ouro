from agent.agent import LoopAgent


def test_extract_task_dump_md_request_parses_path_and_debug() -> None:
    agent = LoopAgent.__new__(LoopAgent)
    task = '请在最后调用 TaskDumpMd(path=".tmp/tasks.md", includeDebug=true)。'
    assert agent._extract_task_dump_md_request(task) == (".tmp/tasks.md", True)


def test_extract_task_dump_md_request_parses_path_without_debug() -> None:
    agent = LoopAgent.__new__(LoopAgent)
    task = "最后调用 TaskDumpMd(path='.tmp/tasks.md')"
    assert agent._extract_task_dump_md_request(task) == (".tmp/tasks.md", False)


def test_extract_task_dump_md_request_requires_path() -> None:
    agent = LoopAgent.__new__(LoopAgent)
    assert agent._extract_task_dump_md_request("最后调用 TaskDumpMd(includeDebug=true)") is None
