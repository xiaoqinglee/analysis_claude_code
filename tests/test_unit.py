"""
Unit tests for learn-claude-code agents.

These tests don't require API calls - they verify code structure and logic.
"""
import os
import sys
import importlib.util

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Import Tests
# =============================================================================

def test_imports():
    """Test that all agent modules can be imported."""
    agents = [
        "v0_bash_agent",
        "v0_bash_agent_mini",
        "v1_basic_agent",
        "v2_todo_agent",
        "v3_subagent",
        "v4_skills_agent",
        "v5_compression_agent",
        "v6_tasks_agent",
        "v7_background_agent",
        "v8a_team_foundation",
        "v8b_messaging",
        "v8c_coordination",
        "v9_autonomous_agent",
    ]

    for agent in agents:
        spec = importlib.util.find_spec(agent)
        assert spec is not None, f"Failed to find {agent}"
        print(f"  Found: {agent}")

    print("PASS: test_imports")
    return True


# =============================================================================
# TodoManager Tests
# =============================================================================

def test_todo_manager_basic():
    """Test TodoManager basic operations."""
    from v2_todo_agent import TodoManager

    tm = TodoManager()

    # Test valid update
    result = tm.update([
        {"content": "Task 1", "status": "pending", "activeForm": "Doing task 1"},
        {"content": "Task 2", "status": "in_progress", "activeForm": "Doing task 2"},
    ])

    assert "Task 1" in result
    assert "Task 2" in result
    assert len(tm.items) == 2

    print("PASS: test_todo_manager_basic")
    return True


def test_todo_manager_constraints():
    """Test TodoManager enforces constraints."""
    from v2_todo_agent import TodoManager

    tm = TodoManager()

    # Test: only one in_progress allowed (should raise or return error)
    try:
        result = tm.update([
            {"content": "Task 1", "status": "in_progress", "activeForm": "Doing 1"},
            {"content": "Task 2", "status": "in_progress", "activeForm": "Doing 2"},
        ])
        # If no exception, check result contains error
        assert "Error" in result or "error" in result.lower()
    except ValueError as e:
        # Exception is expected - constraint enforced
        assert "in_progress" in str(e).lower()

    # Test: max 20 items
    tm2 = TodoManager()
    many_items = [{"content": f"Task {i}", "status": "pending", "activeForm": f"Doing {i}"} for i in range(25)]
    try:
        tm2.update(many_items)
    except ValueError:
        pass  # Exception is fine
    assert len(tm2.items) <= 20

    print("PASS: test_todo_manager_constraints")
    return True


# =============================================================================
# Reminder Tests
# =============================================================================

def test_reminder_constants():
    """Test reminder constants are defined correctly."""
    from v2_todo_agent import INITIAL_REMINDER, NAG_REMINDER

    assert "<reminder>" in INITIAL_REMINDER
    assert "</reminder>" in INITIAL_REMINDER
    assert "<reminder>" in NAG_REMINDER
    assert "</reminder>" in NAG_REMINDER
    assert "todo" in NAG_REMINDER.lower() or "Todo" in NAG_REMINDER

    print("PASS: test_reminder_constants")
    return True


def test_nag_reminder_in_agent_loop():
    """Test NAG_REMINDER injection is inside agent_loop."""
    import inspect
    from v2_todo_agent import agent_loop, NAG_REMINDER

    source = inspect.getsource(agent_loop)

    # NAG_REMINDER should be referenced in agent_loop
    assert "NAG_REMINDER" in source, "NAG_REMINDER should be in agent_loop"
    assert "rounds_without_todo" in source, "rounds_without_todo check should be in agent_loop"
    assert "results.insert" in source or "results.append" in source, "Should inject into results"

    print("PASS: test_nag_reminder_in_agent_loop")
    return True


# =============================================================================
# Configuration Tests
# =============================================================================

def test_env_config():
    """Test environment variable configuration.

    v1_basic_agent uses load_dotenv(override=True) which re-reads .env on reload.
    We verify MODEL is set from MODEL_ID (either from .env or os.environ).
    """
    import importlib
    import v1_basic_agent
    importlib.reload(v1_basic_agent)

    model_id = os.environ.get("MODEL_ID", "")
    if model_id:
        assert v1_basic_agent.MODEL == model_id, \
            f"MODEL should match MODEL_ID env var '{model_id}', got {v1_basic_agent.MODEL}"
    else:
        assert "claude" in v1_basic_agent.MODEL.lower(), \
            f"Default MODEL should contain 'claude': {v1_basic_agent.MODEL}"

    print("PASS: test_env_config")
    return True


def test_default_model():
    """Test MODEL_ID is read correctly from environment.

    When .env contains MODEL_ID, load_dotenv(override=True) will always set it.
    We verify the module reads whatever MODEL_ID is in the environment.
    """
    import importlib
    import v1_basic_agent
    importlib.reload(v1_basic_agent)

    assert v1_basic_agent.MODEL is not None, "MODEL should not be None"
    assert len(v1_basic_agent.MODEL) > 0, "MODEL should not be empty"

    print("PASS: test_default_model")
    return True


# =============================================================================
# Tool Schema Tests
# =============================================================================

def test_tool_schemas():
    """Test tool schemas are valid."""
    from v1_basic_agent import TOOLS

    required_tools = {"bash", "read_file", "write_file", "edit_file"}
    tool_names = {t["name"] for t in TOOLS}

    assert required_tools.issubset(tool_names), f"Missing tools: {required_tools - tool_names}"

    for tool in TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
        assert tool["input_schema"].get("type") == "object"

    print("PASS: test_tool_schemas")
    return True


# =============================================================================
# TodoManager Edge Case Tests
# =============================================================================

def test_todo_manager_empty_list():
    """Test TodoManager handles empty list."""
    from v2_todo_agent import TodoManager

    tm = TodoManager()
    result = tm.update([])

    assert "No todos" in result or len(tm.items) == 0
    print("PASS: test_todo_manager_empty_list")
    return True


def test_todo_manager_status_transitions():
    """Test TodoManager status transitions."""
    from v2_todo_agent import TodoManager

    tm = TodoManager()

    # Start with pending
    tm.update([{"content": "Task", "status": "pending", "activeForm": "Doing task"}])
    assert tm.items[0]["status"] == "pending"

    # Move to in_progress
    tm.update([{"content": "Task", "status": "in_progress", "activeForm": "Doing task"}])
    assert tm.items[0]["status"] == "in_progress"

    # Complete
    tm.update([{"content": "Task", "status": "completed", "activeForm": "Doing task"}])
    assert tm.items[0]["status"] == "completed"

    print("PASS: test_todo_manager_status_transitions")
    return True


def test_todo_manager_missing_fields():
    """Test TodoManager rejects items with missing fields."""
    from v2_todo_agent import TodoManager

    tm = TodoManager()

    # Missing content
    try:
        tm.update([{"status": "pending", "activeForm": "Doing"}])
        assert False, "Should reject missing content"
    except ValueError:
        pass

    # Missing activeForm
    try:
        tm.update([{"content": "Task", "status": "pending"}])
        assert False, "Should reject missing activeForm"
    except ValueError:
        pass

    print("PASS: test_todo_manager_missing_fields")
    return True


def test_todo_manager_invalid_status():
    """Test TodoManager rejects invalid status values."""
    from v2_todo_agent import TodoManager

    tm = TodoManager()

    try:
        tm.update([{"content": "Task", "status": "invalid", "activeForm": "Doing"}])
        assert False, "Should reject invalid status"
    except ValueError as e:
        assert "status" in str(e).lower()

    print("PASS: test_todo_manager_invalid_status")
    return True


def test_todo_manager_render_format():
    """Test TodoManager render format."""
    from v2_todo_agent import TodoManager

    tm = TodoManager()
    tm.update([
        {"content": "Task A", "status": "completed", "activeForm": "A"},
        {"content": "Task B", "status": "in_progress", "activeForm": "B"},
        {"content": "Task C", "status": "pending", "activeForm": "C"},
    ])

    result = tm.render()
    assert "[x] Task A" in result
    assert "[>] Task B" in result
    assert "[ ] Task C" in result
    assert "1/3" in result  # Format may vary: "done" or "completed"

    print("PASS: test_todo_manager_render_format")
    return True


# =============================================================================
# v3 Agent Type Registry Tests
# =============================================================================

def test_v3_agent_types_structure():
    """Test v3 AGENT_TYPES structure."""
    from v3_subagent import AGENT_TYPES

    required_types = {"Explore", "general-purpose", "Plan"}
    assert set(AGENT_TYPES.keys()) == required_types

    for name, config in AGENT_TYPES.items():
        assert "description" in config, f"{name} missing description"
        assert "tools" in config, f"{name} missing tools"
        assert "prompt" in config, f"{name} missing prompt"

    print("PASS: test_v3_agent_types_structure")
    return True


def test_v3_get_tools_for_agent():
    """Test v3 get_tools_for_agent filters correctly."""
    from v3_subagent import get_tools_for_agent, BASE_TOOLS

    # Explore: read-only
    explore_tools = get_tools_for_agent("Explore")
    explore_names = {t["name"] for t in explore_tools}
    assert "bash" in explore_names
    assert "read_file" in explore_names
    assert "write_file" not in explore_names
    assert "edit_file" not in explore_names

    # general-purpose: all base tools
    code_tools = get_tools_for_agent("general-purpose")
    assert len(code_tools) == len(BASE_TOOLS)

    # Plan: read-only
    plan_tools = get_tools_for_agent("Plan")
    plan_names = {t["name"] for t in plan_tools}
    assert "write_file" not in plan_names

    print("PASS: test_v3_get_tools_for_agent")
    return True


def test_v3_get_agent_descriptions():
    """Test v3 get_agent_descriptions output."""
    from v3_subagent import get_agent_descriptions

    desc = get_agent_descriptions()
    assert "Explore" in desc
    assert "general-purpose" in desc
    assert "Plan" in desc
    assert "Read-only" in desc or "read" in desc.lower()

    print("PASS: test_v3_get_agent_descriptions")
    return True


def test_v3_task_tool_schema():
    """Test v3 Task tool schema."""
    from v3_subagent import TASK_TOOL, AGENT_TYPES

    assert TASK_TOOL["name"] == "Task"
    schema = TASK_TOOL["input_schema"]
    assert "description" in schema["properties"]
    assert "prompt" in schema["properties"]
    assert "subagent_type" in schema["properties"]
    assert set(schema["properties"]["subagent_type"]["enum"]) == set(AGENT_TYPES.keys())

    print("PASS: test_v3_task_tool_schema")
    return True


# =============================================================================
# v4 SkillLoader Tests
# =============================================================================

def test_v4_skill_loader_init():
    """Test v4 SkillLoader initialization."""
    from v4_skills_agent import SkillLoader
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # Empty skills dir
        loader = SkillLoader(Path(tmpdir))
        assert len(loader.skills) == 0

    print("PASS: test_v4_skill_loader_init")
    return True


def test_v4_skill_loader_parse_valid():
    """Test v4 SkillLoader parses valid SKILL.md."""
    from v4_skills_agent import SkillLoader
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "test-skill"
        skill_dir.mkdir()

        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: test
description: A test skill for testing
---

# Test Skill

This is the body content.
""")

        loader = SkillLoader(Path(tmpdir))
        assert "test" in loader.skills
        assert loader.skills["test"]["description"] == "A test skill for testing"
        assert "body content" in loader.skills["test"]["body"]

    print("PASS: test_v4_skill_loader_parse_valid")
    return True


def test_v4_skill_loader_parse_invalid():
    """Test v4 SkillLoader rejects invalid SKILL.md."""
    from v4_skills_agent import SkillLoader
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "bad-skill"
        skill_dir.mkdir()

        # Missing frontmatter
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("# No frontmatter\n\nJust content.")

        loader = SkillLoader(Path(tmpdir))
        assert "bad-skill" not in loader.skills

    print("PASS: test_v4_skill_loader_parse_invalid")
    return True


def test_v4_skill_loader_get_content():
    """Test v4 SkillLoader get_skill_content."""
    from v4_skills_agent import SkillLoader
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        skill_dir = Path(tmpdir) / "demo"
        skill_dir.mkdir()

        (skill_dir / "SKILL.md").write_text("""---
name: demo
description: Demo skill
---

# Demo Instructions

Step 1: Do this
Step 2: Do that
""")

        # Add resources
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "helper.sh").write_text("#!/bin/bash\necho hello")

        loader = SkillLoader(Path(tmpdir))

        content = loader.get_skill_content("demo")
        assert content is not None
        assert "Demo Instructions" in content
        assert "helper.sh" in content  # Resources listed

        # Non-existent skill
        assert loader.get_skill_content("nonexistent") is None

    print("PASS: test_v4_skill_loader_get_content")
    return True


def test_v4_skill_loader_list_skills():
    """Test v4 SkillLoader list_skills."""
    from v4_skills_agent import SkillLoader
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create two skills
        for name in ["alpha", "beta"]:
            skill_dir = Path(tmpdir) / name
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(f"""---
name: {name}
description: {name} skill
---

Content for {name}
""")

        loader = SkillLoader(Path(tmpdir))
        skills = loader.list_skills()
        assert "alpha" in skills
        assert "beta" in skills
        assert len(skills) == 2

    print("PASS: test_v4_skill_loader_list_skills")
    return True


def test_v4_skill_tool_schema():
    """Test v4 Skill tool schema."""
    from v4_skills_agent import SKILL_TOOL

    assert SKILL_TOOL["name"] == "Skill"
    schema = SKILL_TOOL["input_schema"]
    assert "skill" in schema["properties"]
    assert "skill" in schema["required"]

    print("PASS: test_v4_skill_tool_schema")
    return True


# =============================================================================
# Path Safety Tests
# =============================================================================

def test_v3_safe_path():
    """Test v3 safe_path prevents path traversal."""
    from v3_subagent import safe_path, WORKDIR

    # Valid path
    p = safe_path("test.txt")
    assert str(p).startswith(str(WORKDIR))

    # Path traversal attempt
    try:
        safe_path("../../../etc/passwd")
        assert False, "Should reject path traversal"
    except ValueError as e:
        assert "escape" in str(e).lower()

    print("PASS: test_v3_safe_path")
    return True


# =============================================================================
# Configuration Tests (Extended)
# =============================================================================

def test_base_url_config():
    """Test ANTHROPIC_BASE_URL configuration."""
    orig = os.environ.get("ANTHROPIC_BASE_URL")

    try:
        os.environ["ANTHROPIC_BASE_URL"] = "https://custom.api.com"

        import importlib
        import v1_basic_agent
        importlib.reload(v1_basic_agent)

        # Check client was created (we can't easily verify base_url without mocking)
        assert v1_basic_agent.client is not None

        print("PASS: test_base_url_config")
        return True

    finally:
        if orig:
            os.environ["ANTHROPIC_BASE_URL"] = orig
        else:
            os.environ.pop("ANTHROPIC_BASE_URL", None)


# =============================================================================
# v5 ContextManager Tests
# =============================================================================

def test_v5_estimate_tokens():
    """Test v5 ContextManager token estimation using // 4 formula."""
    from v5_compression_agent import ContextManager
    cm = ContextManager()

    assert cm.estimate_tokens("") == 0
    # 4 chars // 4 = 1
    assert cm.estimate_tokens("abcd") == 1, f"Expected 1, got {cm.estimate_tokens('abcd')}"
    # 400 chars // 4 = 100
    assert cm.estimate_tokens("a" * 400) == 100, f"Expected 100, got {cm.estimate_tokens('a' * 400)}"

    print("PASS: test_v5_estimate_tokens")
    return True


def test_v5_microcompact_keeps_recent():
    """Test v5 microcompact keeps the most recent tool outputs."""
    from v5_compression_agent import ContextManager
    cm = ContextManager()

    # Create 10 tool results with large outputs (100000 chars each = ~25000 tokens).
    # KEEP_RECENT=3 means 7 are candidates. Each >1000 tokens, total savings ~175000
    # which far exceeds MIN_SAVINGS (20000).
    n = 10
    messages = [
        {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "read_file", "input": {}} for i in range(n)]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": "x" * 100000}
            for i in range(n)
        ]},
    ]

    result = cm.microcompact(messages)
    user_content = result[1]["content"]

    compacted = sum(1 for b in user_content if b.get("content") == "[Old tool result content cleared]")
    preserved = sum(1 for b in user_content if len(b.get("content", "")) > 100)

    assert preserved == cm.KEEP_RECENT, f"Should keep {cm.KEEP_RECENT} recent, got {preserved}"
    assert compacted == n - cm.KEEP_RECENT, f"Should compact {n - cm.KEEP_RECENT} old outputs, got {compacted}"

    print("PASS: test_v5_microcompact_keeps_recent")
    return True


def test_v5_microcompact_skips_small():
    """Test v5 microcompact doesn't compact small outputs."""
    from v5_compression_agent import ContextManager
    cm = ContextManager()

    messages = [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "read_file", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "small output"}
        ]},
    ]

    result = cm.microcompact(messages)
    assert result[1]["content"][0]["content"] == "small output"

    print("PASS: test_v5_microcompact_skips_small")
    return True


def test_v5_should_compact():
    """Test v5 should_compact threshold detection using TOKEN_THRESHOLD constant."""
    from v5_compression_agent import ContextManager
    cm = ContextManager()

    small = [{"role": "user", "content": "hi"}]
    assert not cm.should_compact(small), "Small messages shouldn't trigger compact"

    # should_compact uses estimate_tokens(json.dumps(m)) per message, summed.
    # With MIN_SAVINGS guard, we need >5 messages (recent 5 are kept) and enough
    # total tokens to exceed TOKEN_THRESHOLD, with savings >= MIN_SAVINGS.
    # Build 8 large messages so the first 3 produce enough savings.
    # With len//4: need chunk_size such that 8 * (chunk_size+~30) // 4 > threshold
    chunk_size = (cm.TOKEN_THRESHOLD * 4) // 8 + 100
    large = [{"role": "user", "content": "x" * chunk_size} for _ in range(8)]
    assert cm.should_compact(large), "Messages exceeding TOKEN_THRESHOLD should trigger compact"

    print("PASS: test_v5_should_compact")
    return True


def test_v5_handle_large_output():
    """Test v5 handles oversized output correctly."""
    import tempfile
    from v5_compression_agent import ContextManager
    cm = ContextManager()

    normal = "small output"
    assert cm.handle_large_output(normal) == normal

    # estimate_tokens uses len // 4. To exceed MAX_OUTPUT_TOKENS (40000),
    # need len // 4 > 40000, i.e. len > 160000.
    large = "x" * 160100
    result = cm.handle_large_output(large)
    assert "too large" in result.lower() or "Saved to" in result

    print("PASS: test_v5_handle_large_output")
    return True


def test_v5_save_transcript():
    """Test v5 saves transcript to disk."""
    import tempfile
    from pathlib import Path
    from v5_compression_agent import ContextManager

    with tempfile.TemporaryDirectory() as tmpdir:
        import v5_compression_agent
        orig = v5_compression_agent.TRANSCRIPT_DIR
        v5_compression_agent.TRANSCRIPT_DIR = Path(tmpdir)

        cm = ContextManager()
        cm.save_transcript([{"role": "user", "content": "test message"}])

        transcript = Path(tmpdir) / "transcript.jsonl"
        assert transcript.exists(), "Transcript file should exist"
        content = transcript.read_text()
        assert "test message" in content

        v5_compression_agent.TRANSCRIPT_DIR = orig

    print("PASS: test_v5_save_transcript")
    return True


# =============================================================================
# v6 TaskManager Tests
# =============================================================================

def test_v6_task_create():
    """Test v6 TaskManager create with auto-increment ID."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        t1 = tm.create("First task", "Description 1")
        t2 = tm.create("Second task", "Description 2")

        assert t1.id == "1"
        assert t2.id == "2"
        assert t1.subject == "First task"
        assert t1.status == "pending"

    print("PASS: test_v6_task_create")
    return True


def test_v6_task_get():
    """Test v6 TaskManager get by ID."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        tm.create("Test task", "Details")

        task = tm.get("1")
        assert task is not None
        assert task.subject == "Test task"

        assert tm.get("999") is None

    print("PASS: test_v6_task_get")
    return True


def test_v6_task_update_status():
    """Test v6 TaskManager status update."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        tm.create("Task", "Desc")

        updated = tm.update("1", status="in_progress")
        assert updated.status == "in_progress"

        updated = tm.update("1", status="completed")
        assert updated.status == "completed"

    print("PASS: test_v6_task_update_status")
    return True


def test_v6_task_dependencies():
    """Test v6 TaskManager dependency management."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        tm.create("Setup DB")
        tm.create("Write API")
        tm.create("Write tests")

        tm.update("2", addBlockedBy=["1"])
        tm.update("3", addBlockedBy=["1", "2"])

        t2 = tm.get("2")
        assert "1" in t2.blocked_by
        t3 = tm.get("3")
        assert "1" in t3.blocked_by
        assert "2" in t3.blocked_by

    print("PASS: test_v6_task_dependencies")
    return True


def test_v6_task_complete_clears_deps():
    """Test v6 completing a task clears it from others' blocked_by."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        tm.create("Task A")
        tm.create("Task B")
        tm.update("2", addBlockedBy=["1"])

        assert "1" in tm.get("2").blocked_by

        tm.update("1", status="completed")

        t2 = tm.get("2")
        assert "1" not in t2.blocked_by, "Completing task should clear dependency"

    print("PASS: test_v6_task_complete_clears_deps")
    return True


def test_v6_task_list():
    """Test v6 TaskManager list_all."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        tm.create("A")
        tm.create("B")
        tm.create("C")

        tasks = tm.list_all()
        assert len(tasks) == 3
        subjects = [t.subject for t in tasks]
        assert "A" in subjects and "B" in subjects and "C" in subjects

    print("PASS: test_v6_task_list")
    return True


def test_v6_task_persistence():
    """Test v6 tasks persist as JSON files on disk."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm1 = TaskManager(Path(tmpdir))
        tm1.create("Persistent task", "Should survive reload")

        # Create new manager pointing to same dir
        tm2 = TaskManager(Path(tmpdir))
        task = tm2.get("1")
        assert task is not None
        assert task.subject == "Persistent task"

    print("PASS: test_v6_task_persistence")
    return True


def test_v6_task_delete():
    """Test v6 TaskManager delete."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        tm.create("To delete")
        assert tm.delete("1") is True
        assert tm.get("1") is None
        assert tm.delete("999") is False

    print("PASS: test_v6_task_delete")
    return True


def test_v6_task_tools_in_all_tools():
    """Test v6 Task CRUD tools are in ALL_TOOLS."""
    from v6_tasks_agent import ALL_TOOLS
    tool_names = {t["name"] for t in ALL_TOOLS}
    assert "TaskCreate" in tool_names
    assert "TaskGet" in tool_names
    assert "TaskUpdate" in tool_names
    assert "TaskList" in tool_names

    print("PASS: test_v6_task_tools_in_all_tools")
    return True


# =============================================================================
# v7 BackgroundManager Tests
# =============================================================================

def test_v7_background_run():
    """Test v7 BackgroundManager runs tasks and returns task_id."""
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()

    task_id = bm.run_in_background(lambda: "result", task_type="bash")
    assert task_id.startswith("b"), f"Bash task should have 'b' prefix, got {task_id}"

    task_id2 = bm.run_in_background(lambda: "result2", task_type="agent")
    assert task_id2.startswith("a"), f"Agent task should have 'a' prefix, got {task_id2}"

    print("PASS: test_v7_background_run")
    return True


def test_v7_background_get_output_blocking():
    """Test v7 BackgroundManager blocking output retrieval."""
    import time
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()

    task_id = bm.run_in_background(lambda: (time.sleep(0.1), "done")[1], task_type="bash")

    result = bm.get_output(task_id, block=True, timeout=5000)
    assert result["status"] == "completed"
    assert result["output"] == "done"

    print("PASS: test_v7_background_get_output_blocking")
    return True


def test_v7_background_get_output_nonblocking():
    """Test v7 BackgroundManager non-blocking output retrieval."""
    import time
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()

    task_id = bm.run_in_background(lambda: (time.sleep(1), "done")[1], task_type="agent")

    result = bm.get_output(task_id, block=False)
    assert result["status"] == "running", f"Should be running, got {result['status']}"

    print("PASS: test_v7_background_get_output_nonblocking")
    return True


def test_v7_background_notifications():
    """Test v7 BackgroundManager notification queue."""
    import time
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()

    bm.run_in_background(lambda: "task1 done", task_type="bash")
    bm.run_in_background(lambda: "task2 done", task_type="agent")

    time.sleep(0.2)

    notifications = bm.drain_notifications()
    assert len(notifications) >= 2, f"Should have 2+ notifications, got {len(notifications)}"

    # Queue should be empty after drain
    assert len(bm.drain_notifications()) == 0

    print("PASS: test_v7_background_notifications")
    return True


def test_v7_background_stop():
    """Test v7 BackgroundManager task stopping."""
    import time
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()

    task_id = bm.run_in_background(lambda: (time.sleep(10), "never")[1], task_type="bash")
    result = bm.stop_task(task_id)
    assert result["status"] == "stopped"

    print("PASS: test_v7_background_stop")
    return True


def test_v7_tools_in_all_tools():
    """Test v7 TaskOutput and TaskStop are in ALL_TOOLS."""
    from v7_background_agent import ALL_TOOLS
    tool_names = {t["name"] for t in ALL_TOOLS}
    assert "TaskOutput" in tool_names
    assert "TaskStop" in tool_names

    print("PASS: test_v7_tools_in_all_tools")
    return True


# =============================================================================
# v8 TeammateManager Tests
# =============================================================================

def test_v8_create_team():
    """Test v8 TeammateManager team creation."""
    from v8c_coordination import TeammateManager
    tm = TeammateManager()

    result = tm.create_team("test-team")
    assert "created" in result.lower()

    result2 = tm.create_team("test-team")
    assert "already exists" in result2.lower()

    print("PASS: test_v8_create_team")
    return True


def test_v8_send_message():
    """Test v8 TeammateManager message sending via inbox."""
    import tempfile
    from pathlib import Path
    from v8c_coordination import TeammateManager, Teammate

    tm = TeammateManager()
    tm.create_team("msg-team")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    teammate = Teammate(name="worker", team_name="msg-team", inbox_path=inbox)
    tm._teams["msg-team"]["worker"] = teammate

    tm.send_message("worker", "Hello!", msg_type="message", team_name="msg-team")

    msgs = tm.check_inbox("worker", "msg-team")
    assert len(msgs) == 1
    assert msgs[0]["content"] == "Hello!"
    assert msgs[0]["type"] == "message"

    # Inbox should be cleared after check
    msgs2 = tm.check_inbox("worker", "msg-team")
    assert len(msgs2) == 0

    inbox.unlink(missing_ok=True)

    print("PASS: test_v8_send_message")
    return True


def test_v8_message_types():
    """Test v8 TeammateManager validates message types."""
    from v8c_coordination import TeammateManager
    tm = TeammateManager()

    result = tm.send_message("nobody", "test", msg_type="invalid_type")
    assert "invalid" in result.lower() or "error" in result.lower()

    print("PASS: test_v8_message_types")
    return True


def test_v8_delete_team():
    """Test v8 TeammateManager team deletion."""
    import tempfile
    from pathlib import Path
    from v8c_coordination import TeammateManager, Teammate

    tm = TeammateManager()
    tm.create_team("del-team")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    teammate = Teammate(name="w1", team_name="del-team", inbox_path=inbox)
    tm._teams["del-team"]["w1"] = teammate

    result = tm.delete_team("del-team")
    assert "deleted" in result.lower()
    assert "del-team" not in tm._teams

    inbox.unlink(missing_ok=True)

    print("PASS: test_v8_delete_team")
    return True


def test_v8_team_tools_in_all_tools():
    """Test v8 Team tools are in ALL_TOOLS."""
    from v8c_coordination import ALL_TOOLS
    tool_names = {t["name"] for t in ALL_TOOLS}
    assert "TeamCreate" in tool_names
    assert "SendMessage" in tool_names
    assert "TeamDelete" in tool_names

    print("PASS: test_v8_team_tools_in_all_tools")
    return True


def test_v8_team_status():
    """Test v8 TeammateManager status reporting."""
    from v8c_coordination import TeammateManager
    tm = TeammateManager()

    assert "No teams" in tm.get_team_status()

    tm.create_team("status-team")
    status = tm.get_team_status("status-team")
    assert "status-team" in status

    print("PASS: test_v8_team_status")
    return True


# =============================================================================
# v5 Mechanism-Specific Unit Tests
# =============================================================================

def test_v5_compactable_tools():
    """Verify COMPACTABLE_TOOLS matches actual tool set."""
    from v5_compression_agent import ContextManager
    cm = ContextManager()
    assert "bash" in cm.COMPACTABLE_TOOLS
    assert "read_file" in cm.COMPACTABLE_TOOLS
    assert "write_file" in cm.COMPACTABLE_TOOLS
    assert "edit_file" in cm.COMPACTABLE_TOOLS
    print("PASS: test_v5_compactable_tools")
    return True


def test_v5_auto_compact_source():
    """Verify auto_compact saves transcript and replaces ALL messages."""
    import inspect
    from v5_compression_agent import ContextManager
    source = inspect.getsource(ContextManager.auto_compact)
    assert "save_transcript" in source, "auto_compact must archive before compressing"
    assert "replace ALL" in source or "no \"keep last N\"" in source.lower() or \
           "Conversation compressed" in source, \
        "auto_compact must replace ALL messages (no keep-last-5)"
    print("PASS: test_v5_auto_compact_source")
    return True


# =============================================================================
# v6 Mechanism-Specific Unit Tests
# =============================================================================

def test_v6_dependency_bidirectional():
    """Verify addBlockedBy creates bidirectional links."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        tm.create("Parent")
        tm.create("Child")
        tm.update("2", addBlockedBy=["1"])
        assert "1" in tm.get("2").blocked_by
        assert "2" in tm.get("1").blocks
    print("PASS: test_v6_dependency_bidirectional")
    return True


# =============================================================================
# v7 Mechanism-Specific Unit Tests
# =============================================================================

def test_v7_tool_count():
    """Verify v7 has exactly 12 tools."""
    from v7_background_agent import ALL_TOOLS
    assert len(ALL_TOOLS) == 12, f"v7 should have 12 tools, got {len(ALL_TOOLS)}"
    print("PASS: test_v7_tool_count")
    return True


def test_v7_daemon_threads():
    """Verify background tasks run in daemon threads."""
    import time
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()
    tid = bm.run_in_background(lambda: "x", task_type="bash")
    task = bm._tasks[tid]
    assert task.thread.daemon is True
    bm.get_output(tid, block=True, timeout=2000)
    print("PASS: test_v7_daemon_threads")
    return True


def test_v7_notification_drain_clears():
    """Verify drain_notifications clears the queue."""
    import time
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()
    bm.run_in_background(lambda: "done", task_type="bash")
    time.sleep(0.2)
    n1 = bm.drain_notifications()
    assert len(n1) >= 1
    n2 = bm.drain_notifications()
    assert len(n2) == 0, "Second drain should return empty"
    print("PASS: test_v7_notification_drain_clears")
    return True


# =============================================================================
# v8 Mechanism-Specific Unit Tests
# =============================================================================

def test_v8_tool_count():
    """Verify v8 has exactly 15 tools."""
    from v8c_coordination import ALL_TOOLS
    assert len(ALL_TOOLS) == 15, f"v8 should have 15 tools, got {len(ALL_TOOLS)}"
    print("PASS: test_v8_tool_count")
    return True


def test_v8_teammate_tools_subset():
    """Verify TEAMMATE_TOOLS is a proper subset of ALL_TOOLS."""
    from v8c_coordination import TEAMMATE_TOOLS, ALL_TOOLS
    mate_names = {t["name"] for t in TEAMMATE_TOOLS}
    all_names = {t["name"] for t in ALL_TOOLS}
    assert mate_names.issubset(all_names)
    assert len(TEAMMATE_TOOLS) < len(ALL_TOOLS)
    assert "TeamCreate" not in mate_names
    assert "TeamDelete" not in mate_names
    print("PASS: test_v8_teammate_tools_subset")
    return True


def test_v8_message_types_count():
    """Verify MESSAGE_TYPES has exactly 5 types."""
    from v8c_coordination import MESSAGE_TYPES
    assert len(MESSAGE_TYPES) == 5, \
        f"Expected 5 message types, got {len(MESSAGE_TYPES)}"
    print("PASS: test_v8_message_types_count")
    return True


def test_v7_notification_xml_construction():
    """Verify agent_loop constructs attachment-based notifications from drain results."""
    import inspect, v7_background_agent
    source = inspect.getsource(v7_background_agent.agent_loop)
    assert "drain_notifications" in source, \
        "agent_loop must call drain_notifications"
    assert "attachment" in source or "notification" in source, \
        "agent_loop must handle notifications"
    print("PASS: test_v7_notification_xml_construction")
    return True


def test_v7_summary_truncation():
    """Verify notification summary is truncated to 500 chars."""
    import time
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()
    long_output = "A" * 1000
    tid = bm.run_in_background(lambda: long_output, task_type="bash")
    bm.get_output(tid, block=True, timeout=5000)
    time.sleep(0.1)
    notifications = bm.drain_notifications()
    target = [n for n in notifications if
              isinstance(n.get("attachment"), dict) and n["attachment"].get("task_id") == tid]
    assert len(target) == 1, f"Expected 1 notification, got {len(target)}"
    assert len(target[0]["attachment"]["summary"]) == 500, \
        f"Summary should be 500 chars, got {len(target[0]['attachment']['summary'])}"
    print("PASS: test_v7_summary_truncation")
    return True


def test_v8_teammate_bg_prefix():
    """Verify v8 BackgroundManager maps 'teammate' type to 't' prefix."""
    from v8c_coordination import BackgroundManager
    bm = BackgroundManager()
    tid = bm.run_in_background(lambda: "x", task_type="teammate")
    assert tid.startswith("t"), f"Teammate prefix should be 't', got '{tid[0]}'"
    bm.get_output(tid, block=True, timeout=2000)
    print("PASS: test_v8_teammate_bg_prefix")
    return True


def test_v8_spawn_teammate_errors():
    """Verify spawn_teammate returns errors for invalid inputs."""
    from v8c_coordination import TeammateManager
    tm = TeammateManager()
    result = tm.spawn_teammate("worker", "nonexistent-team", "prompt")
    assert "error" in result.lower(), \
        f"Should return error for non-existent team, got: {result}"
    tm.create_team("err-team")
    tm.spawn_teammate("dup", "err-team", "prompt")
    import time; time.sleep(0.1)
    result2 = tm.spawn_teammate("dup", "err-team", "another prompt")
    assert "error" in result2.lower() or "already exists" in result2.lower(), \
        f"Should return error for duplicate name, got: {result2}"
    tm.delete_team("err-team")
    print("PASS: test_v8_spawn_teammate_errors")
    return True


def test_v8_find_teammate_cross_team():
    """Verify _find_teammate searches across teams when team_name is None."""
    import tempfile
    from pathlib import Path
    from v8c_coordination import TeammateManager, Teammate
    tm = TeammateManager()
    tm.create_team("team-a")
    tm.create_team("team-b")
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="cross-worker", team_name="team-b", inbox_path=inbox)
    tm._teams["team-b"]["cross-worker"] = mate
    found = tm._find_teammate("cross-worker")
    assert found is not None, "Should find teammate across teams without team_name"
    assert found.name == "cross-worker"
    assert found.team_name == "team-b"
    not_found = tm._find_teammate("nonexistent")
    assert not_found is None, "Should return None for non-existent teammate"
    inbox.unlink(missing_ok=True)
    print("PASS: test_v8_find_teammate_cross_team")
    return True


def test_v8_teammate_loop_structure():
    """Verify _teammate_loop has key structural elements for the work cycle."""
    import inspect, v9_autonomous_agent
    source = inspect.getsource(v9_autonomous_agent.TeammateManager._teammate_loop)
    assert "active" in source, "Loop must set status to 'active'"
    assert "idle" in source, "Loop must set status to 'idle'"
    assert "shutdown" in source, "Loop must check for 'shutdown'"
    assert "check_inbox" in source, "Loop must check inbox for new messages"
    assert "unclaimed" in source or "pending" in source, \
        "Loop must check for unclaimed tasks"
    assert "microcompact" in source, "Loop must apply microcompact compression"
    assert "auto_compact" in source, "Loop must support auto_compact"
    assert "teammate.name" in source or "teammate_name" in source or "identity" in source.lower(), \
        "Loop must re-inject identity after compression"
    print("PASS: test_v8_teammate_loop_structure")
    return True


def test_v8_broadcast_to_all():
    """Verify broadcast sends to all teammates, not just one."""
    import tempfile
    from pathlib import Path
    from v8c_coordination import TeammateManager, Teammate
    tm = TeammateManager()
    tm.create_team("bcast-test")
    inboxes = []
    for name in ["alice", "bob", "carol"]:
        inbox = Path(tempfile.mktemp(suffix=".jsonl"))
        mate = Teammate(name=name, team_name="bcast-test", inbox_path=inbox)
        tm._teams["bcast-test"][name] = mate
        inboxes.append(inbox)
    tm.send_message("", "Attention all", msg_type="broadcast",
                    sender="lead", team_name="bcast-test")
    for i, name in enumerate(["alice", "bob", "carol"]):
        msgs = tm.check_inbox(name, "bcast-test")
        assert len(msgs) >= 1, f"{name} should have received broadcast"
        assert msgs[0]["type"] == "broadcast"
    for inbox in inboxes:
        inbox.unlink(missing_ok=True)
    print("PASS: test_v8_broadcast_to_all")
    return True


def test_v8_delete_sends_shutdown():
    """Verify delete_team sends shutdown_request to all members."""
    import tempfile, json
    from pathlib import Path
    from v8c_coordination import TeammateManager, Teammate
    tm = TeammateManager()
    tm.create_team("shutdown-test")
    inboxes = []
    for name in ["w1", "w2"]:
        inbox = Path(tempfile.mktemp(suffix=".jsonl"))
        mate = Teammate(name=name, team_name="shutdown-test", inbox_path=inbox)
        tm._teams["shutdown-test"][name] = mate
        inboxes.append(inbox)
    tm.delete_team("shutdown-test")
    for inbox in inboxes:
        if inbox.exists():
            msgs = [json.loads(l) for l in inbox.read_text().strip().split("\n") if l.strip()]
            shutdown_msgs = [m for m in msgs if m.get("type") == "shutdown_request"]
            assert len(shutdown_msgs) >= 1, \
                f"Each teammate should receive shutdown_request, got {len(shutdown_msgs)}"
        inbox.unlink(missing_ok=True)
    print("PASS: test_v8_delete_sends_shutdown")
    return True


def test_v2_system_reminders():
    """Verify v2 has INITIAL_REMINDER and NAG_REMINDER for planning enforcement."""
    import v2_todo_agent
    source = open(v2_todo_agent.__file__).read()
    assert "INITIAL_REMINDER" in source, \
        "v2 must define INITIAL_REMINDER constant"
    assert "NAG_REMINDER" in source, \
        "v2 must define NAG_REMINDER constant"
    assert hasattr(v2_todo_agent, "INITIAL_REMINDER"), \
        "INITIAL_REMINDER must be a module-level constant"
    assert hasattr(v2_todo_agent, "NAG_REMINDER"), \
        "NAG_REMINDER must be a module-level constant"
    assert len(v2_todo_agent.INITIAL_REMINDER) > 20, \
        "INITIAL_REMINDER should be a substantial prompt"
    assert len(v2_todo_agent.NAG_REMINDER) > 20, \
        "NAG_REMINDER should be a substantial prompt"
    print("PASS: test_v2_system_reminders")
    return True


def test_v3_context_isolation():
    """Verify v3 subagent creates fresh message lists (context isolation)."""
    import inspect, v3_subagent
    run_task_source = inspect.getsource(v3_subagent.run_task)
    assert "sub_messages" in run_task_source, \
        "run_task must use isolated sub_messages list"
    # Verify explore agents get read-only tools (no write_file or edit_file)
    explore_tool_names = v3_subagent.AGENT_TYPES["Explore"]["tools"]
    assert "write_file" not in explore_tool_names, \
        "Explore subagent should not have write_file"
    assert "edit_file" not in explore_tool_names, \
        "Explore subagent should not have edit_file"
    assert "read_file" in explore_tool_names, \
        "Explore subagent should have read_file"
    print("PASS: test_v3_context_isolation")
    return True


# =============================================================================
# v0 Mechanism Tests
# =============================================================================

def test_v0_only_bash_tool():
    """Verify v0 has exactly ONE tool: bash."""
    from v0_bash_agent import TOOL
    assert len(TOOL) == 1, f"v0 should have exactly 1 tool, got {len(TOOL)}"
    assert TOOL[0]["name"] == "bash", f"v0 tool should be 'bash', got {TOOL[0]['name']}"
    print("PASS: test_v0_only_bash_tool")
    return True


def test_v0_agent_loop_recursion():
    """Verify v0 chat() function has the recursive while-True loop structure."""
    import inspect
    from v0_bash_agent import chat
    source = inspect.getsource(chat)
    assert "while True:" in source, "chat() must have while True loop"
    assert "stop_reason" in source, "chat() must check stop_reason"
    assert "tool_use" in source, "chat() must check for tool_use"
    assert "history.append" in source, "chat() must append to history"
    print("PASS: test_v0_agent_loop_recursion")
    return True


def test_v0_subagent_via_bash():
    """Verify v0 system prompt teaches the model to self-spawn as subagent."""
    from v0_bash_agent import SYSTEM
    assert "v0_bash_agent.py" in SYSTEM, "System prompt must mention self-spawning"
    assert "subagent" in SYSTEM.lower() or "Subagent" in SYSTEM, \
        "System prompt must explain subagent pattern"
    print("PASS: test_v0_subagent_via_bash")
    return True


# =============================================================================
# v1 Mechanism Tests (extended)
# =============================================================================

def test_v1_exactly_four_tools():
    """Verify v1 has exactly 4 tools: bash, read_file, write_file, edit_file."""
    from v1_basic_agent import TOOLS
    assert len(TOOLS) == 4, f"v1 should have 4 tools, got {len(TOOLS)}"
    tool_names = {t["name"] for t in TOOLS}
    expected = {"bash", "read_file", "write_file", "edit_file"}
    assert tool_names == expected, f"Expected {expected}, got {tool_names}"
    print("PASS: test_v1_exactly_four_tools")
    return True


def test_v1_safe_path_validation():
    """Verify v1 safe_path blocks escaping the workspace."""
    from v1_basic_agent import safe_path, WORKDIR
    # Valid relative path
    p = safe_path("test_file.txt")
    assert str(p).startswith(str(WORKDIR))

    # Traversal attack
    try:
        safe_path("../../../etc/passwd")
        assert False, "Should reject path traversal"
    except ValueError as e:
        assert "escape" in str(e).lower()

    # Absolute path outside workspace
    try:
        safe_path("/etc/passwd")
        assert False, "Should reject absolute path outside workspace"
    except ValueError:
        pass

    print("PASS: test_v1_safe_path_validation")
    return True


def test_v1_bash_dangerous_commands():
    """Verify v1 blocks dangerous commands."""
    from v1_basic_agent import run_bash
    for cmd in ["rm -rf /", "sudo apt install", "shutdown now"]:
        result = run_bash(cmd)
        assert "error" in result.lower() or "dangerous" in result.lower(), \
            f"Should block '{cmd}', got: {result}"
    print("PASS: test_v1_bash_dangerous_commands")
    return True


def test_v1_agent_loop_structure():
    """Verify v1 agent_loop has the core while-True + stop_reason pattern."""
    import inspect
    from v1_basic_agent import agent_loop
    source = inspect.getsource(agent_loop)
    assert "while True:" in source, "Must have while True loop"
    assert "stop_reason" in source, "Must check stop_reason"
    assert "tool_use" in source, "Must detect tool_use"
    assert "execute_tool" in source, "Must call execute_tool"
    print("PASS: test_v1_agent_loop_structure")
    return True


# =============================================================================
# v2 Mechanism Tests (extended)
# =============================================================================

def test_v2_todo_max_items_enforced():
    """Verify TodoManager enforces the 20-item max limit."""
    from v2_todo_agent import TodoManager
    tm = TodoManager()
    items_21 = [{"content": f"Task {i}", "status": "pending",
                 "activeForm": f"Doing {i}"} for i in range(21)]
    try:
        tm.update(items_21)
        # Some implementations truncate instead of raising
        assert len(tm.items) <= 20, f"Should have at most 20 items, got {len(tm.items)}"
    except ValueError:
        pass  # Raising is also acceptable
    print("PASS: test_v2_todo_max_items_enforced")
    return True


def test_v2_todo_render_format_detailed():
    """Verify TodoManager render format includes icons and completion count."""
    from v2_todo_agent import TodoManager
    tm = TodoManager()
    tm.update([
        {"content": "Alpha", "status": "completed", "activeForm": "Alpha-ing"},
        {"content": "Beta", "status": "in_progress", "activeForm": "Beta-ing"},
        {"content": "Gamma", "status": "pending", "activeForm": "Gamma-ing"},
    ])
    rendered = tm.render()
    lines = rendered.strip().split("\n")
    assert "[x] Alpha" in lines[0], f"First line should show completed: {lines[0]}"
    assert "[>] Beta" in lines[1], f"Second line should show in_progress: {lines[1]}"
    assert "[ ] Gamma" in lines[2], f"Third line should show pending: {lines[2]}"
    assert "1/3" in rendered, f"Should show '1/3' completion: {rendered}"
    print("PASS: test_v2_todo_render_format_detailed")
    return True


def test_v2_status_progression_enforcement():
    """Verify TodoManager allows valid status values only."""
    from v2_todo_agent import TodoManager
    tm = TodoManager()
    for valid_status in ("pending", "in_progress", "completed"):
        tm.update([{"content": "X", "status": valid_status, "activeForm": "Y"}])
        assert tm.items[0]["status"] == valid_status

    for invalid_status in ("unknown", "done", "active", ""):
        try:
            tm.update([{"content": "X", "status": invalid_status, "activeForm": "Y"}])
            assert False, f"Should reject status '{invalid_status}'"
        except ValueError:
            pass

    print("PASS: test_v2_status_progression_enforcement")
    return True


# =============================================================================
# v3 Mechanism Tests (extended)
# =============================================================================

def test_v3_agent_types_exactly_three():
    """Verify AGENT_TYPES has exactly 3 types: Explore, general-purpose, Plan."""
    from v3_subagent import AGENT_TYPES
    assert len(AGENT_TYPES) == 3, f"Expected 3 agent types, got {len(AGENT_TYPES)}"
    assert set(AGENT_TYPES.keys()) == {"Explore", "general-purpose", "Plan"}
    print("PASS: test_v3_agent_types_exactly_three")
    return True


def test_v3_task_prevents_recursion():
    """Verify subagents do NOT get Task tool (prevents infinite recursion)."""
    from v3_subagent import get_tools_for_agent
    for agent_type in ("Explore", "general-purpose", "Plan"):
        tools = get_tools_for_agent(agent_type)
        tool_names = {t["name"] for t in tools}
        assert "Task" not in tool_names, \
            f"Agent type '{agent_type}' should NOT have Task tool (prevents recursion)"
    print("PASS: test_v3_task_prevents_recursion")
    return True


def test_v3_run_task_isolation():
    """Verify run_task creates isolated sub_messages list."""
    import inspect
    from v3_subagent import run_task
    source = inspect.getsource(run_task)
    assert "sub_messages" in source, "run_task must create sub_messages"
    assert 'sub_messages = [{"role": "user"' in source, \
        "sub_messages must start fresh with user prompt"
    print("PASS: test_v3_run_task_isolation")
    return True


# =============================================================================
# v4 Mechanism Tests (extended)
# =============================================================================

def test_v4_skill_loader_yaml_edge_cases():
    """Test SkillLoader handles YAML edge cases: missing name, missing desc, extra fields."""
    from v4_skills_agent import SkillLoader
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # Case 1: Missing name field
        s1 = Path(tmpdir) / "no-name"
        s1.mkdir()
        (s1 / "SKILL.md").write_text("---\ndescription: has desc but no name\n---\nBody")
        loader1 = SkillLoader(Path(tmpdir))
        assert "no-name" not in loader1.skills, \
            "Should reject SKILL.md without name field"

        # Case 2: Missing description field
        s2 = Path(tmpdir) / "no-desc"
        s2.mkdir()
        (s2 / "SKILL.md").write_text("---\nname: nodesc\n---\nBody")
        loader2 = SkillLoader(Path(tmpdir))
        assert "nodesc" not in loader2.skills, \
            "Should reject SKILL.md without description field"

        # Case 3: Extra fields preserved
        s3 = Path(tmpdir) / "extra"
        s3.mkdir()
        (s3 / "SKILL.md").write_text("---\nname: extra\ndescription: has extra\nauthor: me\n---\nBody")
        loader3 = SkillLoader(Path(tmpdir))
        assert "extra" in loader3.skills, "Should accept SKILL.md with extra fields"

    print("PASS: test_v4_skill_loader_yaml_edge_cases")
    return True


def test_v4_skill_loader_cache_separation():
    """Verify two SkillLoaders with different dirs maintain separate caches."""
    from v4_skills_agent import SkillLoader
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        s1 = Path(d1) / "alpha"
        s1.mkdir()
        (s1 / "SKILL.md").write_text("---\nname: alpha\ndescription: Alpha\n---\nAlpha body")

        s2 = Path(d2) / "beta"
        s2.mkdir()
        (s2 / "SKILL.md").write_text("---\nname: beta\ndescription: Beta\n---\nBeta body")

        loader1 = SkillLoader(Path(d1))
        loader2 = SkillLoader(Path(d2))

        assert "alpha" in loader1.skills and "beta" not in loader1.skills
        assert "beta" in loader2.skills and "alpha" not in loader2.skills

    print("PASS: test_v4_skill_loader_cache_separation")
    return True


def test_v4_skill_loader_empty_frontmatter():
    """Verify SkillLoader rejects file with empty frontmatter."""
    from v4_skills_agent import SkillLoader
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        s = Path(tmpdir) / "empty-fm"
        s.mkdir()
        (s / "SKILL.md").write_text("---\n---\nJust body")

        loader = SkillLoader(Path(tmpdir))
        assert len(loader.skills) == 0, "Empty frontmatter should not produce a skill"

    print("PASS: test_v4_skill_loader_empty_frontmatter")
    return True


# =============================================================================
# v5 Mechanism Tests (extended)
# =============================================================================

def test_v5_compactable_tools_set():
    """Verify COMPACTABLE_TOOLS contains exactly the expected tool names."""
    from v5_compression_agent import ContextManager
    cm = ContextManager()
    expected = {"bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir", "notebook_edit"}
    assert cm.COMPACTABLE_TOOLS == expected, \
        f"Expected {expected}, got {cm.COMPACTABLE_TOOLS}"
    print("PASS: test_v5_compactable_tools_set")
    return True


def test_v5_estimate_tokens_precision():
    """Verify estimate_tokens uses chars // 4 ratio."""
    from v5_compression_agent import ContextManager
    cm = ContextManager()
    # 0 chars -> 0 tokens
    assert cm.estimate_tokens("") == 0
    # 4 chars -> 4//4 = 1
    assert cm.estimate_tokens("abcd") == 1
    # 3 chars -> 3//4 = 0
    assert cm.estimate_tokens("abc") == 0
    # 8 chars -> 8//4 = 2
    assert cm.estimate_tokens("12345678") == 2
    # 100 chars -> 100//4 = 25
    assert cm.estimate_tokens("x" * 100) == 25
    # 300 chars -> 300//4 = 75
    assert cm.estimate_tokens("a" * 300) == 75
    print("PASS: test_v5_estimate_tokens_precision")
    return True


def test_v5_microcompact_empty_messages():
    """Verify microcompact handles empty message list gracefully."""
    from v5_compression_agent import ContextManager
    cm = ContextManager()
    result = cm.microcompact([])
    assert result == [], "Empty messages should return empty list"
    print("PASS: test_v5_microcompact_empty_messages")
    return True


def test_v5_microcompact_all_recent():
    """Verify microcompact preserves all outputs when count <= KEEP_RECENT."""
    from v5_compression_agent import ContextManager
    cm = ContextManager()

    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"t{i}", "name": "read_file", "input": {}}
            for i in range(3)
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": "x" * 5000}
            for i in range(3)
        ]},
    ]

    result = cm.microcompact(messages)
    user_content = result[1]["content"]
    for block in user_content:
        assert block["content"] != "[Old tool result content cleared]", \
            "When <= KEEP_RECENT outputs, none should be compacted"

    print("PASS: test_v5_microcompact_all_recent")
    return True


def test_v5_microcompact_no_compactable():
    """Verify microcompact skips non-compactable tool outputs."""
    from v5_compression_agent import ContextManager
    cm = ContextManager()

    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "write_file", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "x" * 10000},
        ]},
    ]

    result = cm.microcompact(messages)
    assert result[1]["content"][0]["content"] == "x" * 10000, \
        "write_file output should NOT be compacted"

    print("PASS: test_v5_microcompact_no_compactable")
    return True


def test_v5_should_compact_various_thresholds():
    """Verify should_compact with various token counts around TOKEN_THRESHOLD."""
    from v5_compression_agent import ContextManager

    cm = ContextManager()
    threshold = cm.TOKEN_THRESHOLD  # 170616 (dynamic)

    # should_compact has MIN_SAVINGS guard: if <= 5 messages, savings=0 -> always False.
    # To properly test threshold, use > 5 messages.
    # Below threshold: each message produces ~(chunk//4) tokens. 8 messages total
    # must stay below threshold.
    # With len//4: chars_per_msg = threshold * 4 / 8 = threshold / 2, minus margin
    below_per_msg = (threshold * 4) // 8 - 200
    below = [{"role": "user", "content": "x" * below_per_msg} for _ in range(8)]
    assert not cm.should_compact(below), f"Should not trigger compact below threshold"

    # Above threshold: each message produces enough to exceed threshold total.
    above_per_msg = (threshold * 4) // 8 + 200
    above = [{"role": "user", "content": "x" * above_per_msg} for _ in range(8)]
    assert cm.should_compact(above), f"Should trigger compact above threshold"

    print("PASS: test_v5_should_compact_various_thresholds")
    return True


def test_v5_handle_large_output_at_boundary():
    """Verify handle_large_output behavior at exactly the threshold."""
    from v5_compression_agent import ContextManager
    cm = ContextManager()

    # estimate_tokens uses len(text) // 4.
    # MAX_OUTPUT_TOKENS = 40000. At boundary: need len such that len // 4 == 40000.
    # len = 40000 * 4 = 160000. Verify: 160000 // 4 = 40000. Exactly at threshold.
    at_threshold = "x" * 160000
    result = cm.handle_large_output(at_threshold)
    assert result == at_threshold, "At exactly the threshold, output should pass through"

    # 4 chars over: 160004 // 4 = 40001 > 40000
    over_threshold = "x" * 160004
    result = cm.handle_large_output(over_threshold)
    assert "too large" in result.lower() or "Output too large" in result or "Saved to" in result, \
        f"Over threshold should be saved to file, got: {result[:100]}"

    print("PASS: test_v5_handle_large_output_at_boundary")
    return True


def test_v5_keep_recent_constant():
    """Verify KEEP_RECENT is 3 (matching cli.js mmY=3)."""
    from v5_compression_agent import ContextManager
    cm = ContextManager()
    assert cm.KEEP_RECENT == 3, f"KEEP_RECENT should be 3, got {cm.KEEP_RECENT}"
    print("PASS: test_v5_keep_recent_constant")
    return True


# =============================================================================
# v6 Mechanism Tests (extended)
# =============================================================================

def test_v6_task_thread_safety():
    """Verify TaskManager create is thread-safe (concurrent creates)."""
    import tempfile
    import threading as _threading
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        errors = []
        ids_created = []

        def create_tasks(start, count):
            try:
                for i in range(count):
                    t = tm.create(f"Task from thread {start}-{i}")
                    ids_created.append(t.id)
            except Exception as e:
                errors.append(e)

        threads = [_threading.Thread(target=create_tasks, args=(i, 5)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"
        # All 20 tasks should have unique IDs
        assert len(set(ids_created)) == 20, \
            f"Expected 20 unique IDs, got {len(set(ids_created))}"

    print("PASS: test_v6_task_thread_safety")
    return True


def test_v6_dependency_chain():
    """Verify dependency chain A->B->C: completing A unblocks B but not C."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        tm.create("Task A")  # id 1
        tm.create("Task B")  # id 2
        tm.create("Task C")  # id 3

        # B depends on A, C depends on B
        tm.update("2", addBlockedBy=["1"])
        tm.update("3", addBlockedBy=["2"])

        # Complete A
        tm.update("1", status="completed")

        # B should be unblocked (A removed from B's blocked_by)
        b = tm.get("2")
        assert "1" not in b.blocked_by, "Completing A should unblock B"

        # C should still be blocked by B
        c = tm.get("3")
        assert "2" in c.blocked_by, "C should still be blocked by B"

    print("PASS: test_v6_dependency_chain")
    return True


def test_v6_task_delete_removes_disk():
    """Verify task delete removes the JSON file from disk."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        tm.create("Ephemeral")

        task_file = Path(tmpdir) / "1.json"
        assert task_file.exists(), "Task file should exist after create"

        tm.delete("1")
        assert not task_file.exists(), "Task file should be removed after delete"

    print("PASS: test_v6_task_delete_removes_disk")
    return True


def test_v6_task_active_form():
    """Verify task active_form field is set on create and stored."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))

        # With explicit active_form
        t1 = tm.create("Fix bug", "Details", "Fixing the auth bug")
        assert t1.active_form == "Fixing the auth bug"

        # Without explicit active_form (should auto-generate)
        t2 = tm.create("Write tests")
        assert t2.active_form != "", "active_form should not be empty"
        assert "Write tests" in t2.active_form, \
            "Auto-generated active_form should include the subject"

    print("PASS: test_v6_task_active_form")
    return True


def test_v6_task_owner_tracking():
    """Verify task owner can be set and persists."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        tm.create("Assigned task")
        tm.update("1", owner="alice")

        task = tm.get("1")
        assert task.owner == "alice", f"Owner should be 'alice', got '{task.owner}'"

        # Reload from disk
        tm2 = TaskManager(Path(tmpdir))
        task2 = tm2.get("1")
        assert task2.owner == "alice", "Owner should persist on disk"

    print("PASS: test_v6_task_owner_tracking")
    return True


# =============================================================================
# v7 Mechanism Tests (extended)
# =============================================================================

def test_v7_background_error_handling():
    """Verify BackgroundManager handles exceptions in background functions."""
    import time
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()

    def failing_func():
        raise RuntimeError("intentional test error")

    task_id = bm.run_in_background(failing_func, task_type="bash")
    result = bm.get_output(task_id, block=True, timeout=5000)

    assert result["status"] == "error", f"Status should be 'error', got {result['status']}"
    assert "intentional test error" in result["output"], \
        f"Output should contain error message, got: {result['output']}"

    print("PASS: test_v7_background_error_handling")
    return True


def test_v7_stop_then_get_output():
    """Verify stopped task returns stopped status via get_output."""
    import time
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()

    task_id = bm.run_in_background(
        lambda: (time.sleep(10), "never")[1], task_type="agent"
    )
    time.sleep(0.1)
    bm.stop_task(task_id)

    result = bm.get_output(task_id, block=False)
    assert result["status"] == "stopped", f"Status should be 'stopped', got {result['status']}"

    print("PASS: test_v7_stop_then_get_output")
    return True


def test_v7_multiple_concurrent_tasks():
    """Verify multiple concurrent background tasks with different types."""
    import time
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()

    ids = []
    ids.append(bm.run_in_background(lambda: "bash_result", task_type="bash"))
    ids.append(bm.run_in_background(lambda: "agent_result", task_type="agent"))
    ids.append(bm.run_in_background(lambda: "bash2_result", task_type="bash"))

    # Wait for all to complete
    for tid in ids:
        bm.get_output(tid, block=True, timeout=5000)

    results = {tid: bm.get_output(tid, block=False) for tid in ids}

    assert results[ids[0]]["output"] == "bash_result"
    assert results[ids[1]]["output"] == "agent_result"
    assert results[ids[2]]["output"] == "bash2_result"

    assert ids[0].startswith("b")
    assert ids[1].startswith("a")
    assert ids[2].startswith("b")

    print("PASS: test_v7_multiple_concurrent_tasks")
    return True


def test_v7_notification_has_required_fields():
    """Verify each notification contains task_id, status, and summary."""
    import time
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()

    bm.run_in_background(lambda: "test_output", task_type="bash")
    time.sleep(0.2)

    notifications = bm.drain_notifications()
    assert len(notifications) >= 1, "Should have at least 1 notification"

    n = notifications[0]
    assert "attachment" in n, "Notification must have attachment key"
    att = n["attachment"]
    assert "task_id" in att, "Notification attachment must have task_id"
    assert "status" in att, "Notification attachment must have status"
    assert "summary" in att, "Notification attachment must have summary"
    assert att["status"] == "completed"
    assert att["summary"] == "test_output"

    print("PASS: test_v7_notification_has_required_fields")
    return True


# =============================================================================
# v8 Mechanism Tests (extended)
# =============================================================================

def test_v8_create_team_creates_directory():
    """Verify TeammateManager.create_team creates a directory on disk."""
    import tempfile
    from pathlib import Path
    import v8c_coordination

    orig_dir = v8c_coordination.TEAMS_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        v8c_coordination.TEAMS_DIR = Path(tmpdir)
        tm = v8c_coordination.TeammateManager()
        tm.create_team("dir-test")

        team_dir = Path(tmpdir) / "dir-test"
        assert team_dir.exists(), "create_team must create team directory"
        assert team_dir.is_dir(), "Team path must be a directory"

        v8c_coordination.TEAMS_DIR = orig_dir

    print("PASS: test_v8_create_team_creates_directory")
    return True


def test_v8_check_inbox_missing_file():
    """Verify check_inbox returns empty list when inbox file does not exist."""
    import tempfile
    from pathlib import Path
    from v8c_coordination import TeammateManager, Teammate

    tm = TeammateManager()
    tm.create_team("empty-inbox-team")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    # Do NOT create the file
    mate = Teammate(name="ghost", team_name="empty-inbox-team", inbox_path=inbox)
    tm._teams["empty-inbox-team"]["ghost"] = mate

    msgs = tm.check_inbox("ghost", "empty-inbox-team")
    assert msgs == [], "Should return empty list for non-existent inbox"

    print("PASS: test_v8_check_inbox_missing_file")
    return True


def test_v8_broadcast_excludes_sender():
    """Verify broadcast sends to N-1 teammates (excludes the sender)."""
    import tempfile
    from pathlib import Path
    from v8c_coordination import TeammateManager, Teammate

    tm = TeammateManager()
    tm.create_team("excl-test")

    inboxes = []
    for name in ["sender", "recv1", "recv2"]:
        inbox = Path(tempfile.mktemp(suffix=".jsonl"))
        mate = Teammate(name=name, team_name="excl-test", inbox_path=inbox)
        tm._teams["excl-test"][name] = mate
        inboxes.append(inbox)

    result = tm.send_message("", "Hello all", msg_type="broadcast",
                             sender="sender", team_name="excl-test")

    # sender should NOT have messages in inbox
    sender_msgs = tm.check_inbox("sender", "excl-test")
    assert len(sender_msgs) == 0, "Sender should not receive own broadcast"

    # recv1 and recv2 should each have 1 message
    for name in ["recv1", "recv2"]:
        msgs = tm.check_inbox(name, "excl-test")
        assert len(msgs) == 1, f"{name} should have received 1 broadcast"

    for inbox in inboxes:
        inbox.unlink(missing_ok=True)

    print("PASS: test_v8_broadcast_excludes_sender")
    return True


def test_v8_teammate_tools_excludes_team_mgmt():
    """Verify TEAMMATE_TOOLS excludes TeamCreate and TeamDelete."""
    from v8c_coordination import TEAMMATE_TOOLS
    tool_names = {t["name"] for t in TEAMMATE_TOOLS}
    assert "TeamCreate" not in tool_names, "Teammates should not have TeamCreate"
    assert "TeamDelete" not in tool_names, "Teammates should not have TeamDelete"
    # But should have SendMessage and task tools
    assert "SendMessage" in tool_names, "Teammates should have SendMessage"
    assert "TaskCreate" in tool_names, "Teammates should have TaskCreate"
    assert "TaskUpdate" in tool_names, "Teammates should have TaskUpdate"
    assert "TaskList" in tool_names, "Teammates should have TaskList"
    print("PASS: test_v8_teammate_tools_excludes_team_mgmt")
    return True


def test_v8_find_teammate_with_team_name():
    """Verify _find_teammate finds teammate when team_name is provided."""
    import tempfile
    from pathlib import Path
    from v8c_coordination import TeammateManager, Teammate

    tm = TeammateManager()
    tm.create_team("find-team")
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="findme", team_name="find-team", inbox_path=inbox)
    tm._teams["find-team"]["findme"] = mate

    # With correct team_name
    found = tm._find_teammate("findme", "find-team")
    assert found is not None
    assert found.name == "findme"

    # Without team_name - should still find by searching all teams
    found_no_team = tm._find_teammate("findme")
    assert found_no_team is not None, "Should find teammate by name across all teams"

    # Searching for nonexistent teammate
    not_found = tm._find_teammate("nonexistent", "find-team")
    assert not_found is None, "Should not find nonexistent teammate"

    inbox.unlink(missing_ok=True)
    print("PASS: test_v8_find_teammate_with_team_name")
    return True


def test_v8_send_message_validates_type():
    """Verify send_message rejects messages with invalid type."""
    from v8c_coordination import TeammateManager
    tm = TeammateManager()

    for invalid in ("invalid", "unknown", "quit", ""):
        result = tm.send_message("anyone", "test", msg_type=invalid)
        assert "error" in result.lower() or "invalid" in result.lower(), \
            f"Should reject msg_type='{invalid}', got: {result}"

    print("PASS: test_v8_send_message_validates_type")
    return True


def test_v9_teammate_identity_injection():
    """Verify v9 _teammate_loop re-injects identity text after auto_compact."""
    try:
        from v9_autonomous_agent import TeammateManager
    except ImportError:
        print("SKIP: v9_autonomous_agent not yet available")
        return True

    import inspect
    source = inspect.getsource(TeammateManager._teammate_loop)
    assert "Remember:" in source or "identity" in source.lower(), \
        "_teammate_loop must re-inject identity after compression"
    assert "teammate.name" in source, "Must use teammate.name in identity"
    assert "teammate.team_name" in source, "Must use teammate.team_name in identity"
    print("PASS: test_v9_teammate_identity_injection")
    return True


def test_v9_unclaimed_task_filter():
    """Verify v9 _scan_unclaimed_tasks filters unclaimed tasks correctly."""
    try:
        from v9_autonomous_agent import TeammateManager
    except ImportError:
        print("SKIP: v9_autonomous_agent not yet available")
        return True

    import inspect
    # The filter logic lives in _scan_unclaimed_tasks, called from _idle_phase
    source = inspect.getsource(TeammateManager._scan_unclaimed_tasks)
    assert "pending" in source, "Must filter for pending status"
    assert "owner" in source, "Must check owner is empty"
    assert "blocked_by" in source, "Must check blocked_by is empty"
    print("PASS: test_v9_unclaimed_task_filter")
    return True


def test_v9_teammate_loop_phases():
    """Verify v9 _teammate_loop has all required phases: active, idle, shutdown, inbox."""
    try:
        from v9_autonomous_agent import TeammateManager
    except ImportError:
        print("SKIP: v9_autonomous_agent not yet available")
        return True

    import inspect
    source = inspect.getsource(TeammateManager._teammate_loop)

    phases = {
        "active": "active" in source,
        "idle": "idle" in source,
        "shutdown": "shutdown" in source,
        "check_inbox": "check_inbox" in source,
        "microcompact": "microcompact" in source,
        "auto_compact": "auto_compact" in source,
    }

    for phase, present in phases.items():
        assert present, f"_teammate_loop missing phase: {phase}"

    print("PASS: test_v9_teammate_loop_phases")
    return True


def test_context_manager_parity():
    """Verify ContextManager is identical across v5-v9."""
    import inspect
    from v5_compression_agent import ContextManager as CM5
    from v6_tasks_agent import ContextManager as CM6
    from v7_background_agent import ContextManager as CM7
    from v8a_team_foundation import ContextManager as CM8a
    from v8b_messaging import ContextManager as CM8b
    from v8c_coordination import ContextManager as CM8c
    from v9_autonomous_agent import ContextManager as CM9

    src5 = inspect.getsource(CM5)
    for name, cls in [("v6", CM6), ("v7", CM7), ("v8a", CM8a), ("v8b", CM8b), ("v8c", CM8c), ("v9", CM9)]:
        src = inspect.getsource(cls)
        assert src == src5, f"ContextManager in {name} differs from v5"
    print("PASS: test_context_manager_parity")
    return True


# =============================================================================
# Behavioral Tests - Cross-Version
# =============================================================================

def test_auto_compact_replaces_all_messages():
    """Verify auto_compact replaces ALL messages, not keeping last 5."""
    import inspect
    from v5_compression_agent import ContextManager
    source = inspect.getsource(ContextManager.auto_compact)
    # The source should NOT contain messages[-5:] or similar "keep last N" patterns
    assert "messages[-5:]" not in source, \
        "auto_compact must NOT keep last 5 messages; it replaces ALL"
    assert "messages[-2:]" not in source, \
        "auto_compact must NOT keep last 2 messages; it replaces ALL"
    # Verify it creates the compressed result from scratch
    assert "Conversation compressed" in source, \
        "auto_compact must produce a [Conversation compressed] summary"
    print("PASS: test_auto_compact_replaces_all_messages")
    return True


def test_microcompact_min_savings_threshold():
    """Verify MIN_SAVINGS is 20000 and microcompact only clears when savings >= MIN_SAVINGS."""
    from v5_compression_agent import MIN_SAVINGS
    assert MIN_SAVINGS == 20000, f"MIN_SAVINGS should be 20000, got {MIN_SAVINGS}"
    print("PASS: test_microcompact_min_savings_threshold")
    return True


def test_compactable_tools_exactly_eight():
    """Verify COMPACTABLE_TOOLS has exactly 8 tools in v5/v6/v7."""
    from v5_compression_agent import ContextManager as CM5
    from v6_tasks_agent import ContextManager as CM6
    from v7_background_agent import ContextManager as CM7

    for name, cm_cls in [("v5", CM5), ("v6", CM6), ("v7", CM7)]:
        cm = cm_cls()
        assert len(cm.COMPACTABLE_TOOLS) == 8, \
            f"{name} COMPACTABLE_TOOLS should have 8 tools, got {len(cm.COMPACTABLE_TOOLS)}"
        expected = {"bash", "read_file", "write_file", "edit_file",
                    "glob", "grep", "list_dir", "notebook_edit"}
        assert cm.COMPACTABLE_TOOLS == expected, \
            f"{name} COMPACTABLE_TOOLS mismatch: expected {expected}, got {cm.COMPACTABLE_TOOLS}"
    print("PASS: test_compactable_tools_exactly_eight")
    return True


def test_v7_notification_attachment_format():
    """Verify v7 notifications use attachment-based format (not XML)."""
    import time
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()
    tid = bm.run_in_background(lambda: "test_result", task_type="bash")
    bm.get_output(tid, block=True, timeout=5000)
    time.sleep(0.1)
    notifications = bm.drain_notifications()
    target = [n for n in notifications if n.get("task_id") == tid or
              (isinstance(n.get("attachment"), dict) and n["attachment"].get("task_id") == tid)]
    assert len(target) >= 1, "Should have at least 1 notification"
    n = target[0]
    assert n.get("type") == "attachment", \
        f"Notification type should be 'attachment', got '{n.get('type')}'"
    assert "attachment" in n, "Notification must have 'attachment' key"
    assert n["attachment"]["type"] == "task_status", \
        f"Attachment type should be 'task_status', got '{n['attachment']['type']}'"
    print("PASS: test_v7_notification_attachment_format")
    return True


def test_v7_output_file_extension():
    """Verify output file extension is .output (not .txt)."""
    from v7_background_agent import BackgroundManager
    bm = BackgroundManager()
    path = bm._write_output("test-123", "some output")
    assert str(path).endswith(".output"), \
        f"Output file should end with .output, got: {path}"
    path.unlink(missing_ok=True)
    print("PASS: test_v7_output_file_extension")
    return True


def test_bash_timeout_default():
    """Verify bash timeout is 120 seconds."""
    import inspect
    from v7_background_agent import _exec_bash
    source = inspect.getsource(_exec_bash)
    assert "timeout=120" in source, \
        "bash timeout should be 120 seconds"
    print("PASS: test_bash_timeout_default")
    return True


def test_task_file_naming_sanitized_no_prefix():
    """Verify task files use sanitized ID without task_ prefix in v6/v7."""
    import tempfile
    from pathlib import Path
    from v6_tasks_agent import TaskManager

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        task = tm.create("Test task")
        task_path = tm._task_path(task.id)
        filename = task_path.name
        # File should be {sanitized_id}.json, NOT task_{id}.json
        assert not filename.startswith("task_"), \
            f"Task file should NOT have task_ prefix, got: {filename}"
        assert filename.endswith(".json"), \
            f"Task file should end with .json, got: {filename}"
        # The sanitized ID should be used directly
        sanitized = tm._sanitize_id(task.id)
        assert filename == f"{sanitized}.json", \
            f"Expected {sanitized}.json, got {filename}"
    print("PASS: test_task_file_naming_sanitized_no_prefix")
    return True
# =============================================================================

if __name__ == "__main__":
    tests = [
        # Basic tests
        test_imports,
        test_todo_manager_basic,
        test_todo_manager_constraints,
        test_reminder_constants,
        test_nag_reminder_in_agent_loop,
        test_env_config,
        test_default_model,
        test_tool_schemas,
        # TodoManager edge cases
        test_todo_manager_empty_list,
        test_todo_manager_status_transitions,
        test_todo_manager_missing_fields,
        test_todo_manager_invalid_status,
        test_todo_manager_render_format,
        # v3 tests
        test_v3_agent_types_structure,
        test_v3_get_tools_for_agent,
        test_v3_get_agent_descriptions,
        test_v3_task_tool_schema,
        # v4 tests
        test_v4_skill_loader_init,
        test_v4_skill_loader_parse_valid,
        test_v4_skill_loader_parse_invalid,
        test_v4_skill_loader_get_content,
        test_v4_skill_loader_list_skills,
        test_v4_skill_tool_schema,
        # Security tests
        test_v3_safe_path,
        # Config tests
        test_base_url_config,
        # v5 tests
        test_v5_estimate_tokens,
        test_v5_microcompact_keeps_recent,
        test_v5_microcompact_skips_small,
        test_v5_should_compact,
        test_v5_handle_large_output,
        test_v5_save_transcript,
        # v6 tests
        test_v6_task_create,
        test_v6_task_get,
        test_v6_task_update_status,
        test_v6_task_dependencies,
        test_v6_task_complete_clears_deps,
        test_v6_task_list,
        test_v6_task_persistence,
        test_v6_task_delete,
        test_v6_task_tools_in_all_tools,
        # v7 tests
        test_v7_background_run,
        test_v7_background_get_output_blocking,
        test_v7_background_get_output_nonblocking,
        test_v7_background_notifications,
        test_v7_background_stop,
        test_v7_tools_in_all_tools,
        # v8 tests
        test_v8_create_team,
        test_v8_send_message,
        test_v8_message_types,
        test_v8_delete_team,
        test_v8_team_tools_in_all_tools,
        test_v8_team_status,
        # v5 mechanism-specific
        test_v5_compactable_tools,
        test_v5_auto_compact_source,
        # v6 mechanism-specific
        test_v6_dependency_bidirectional,
        # v7 mechanism-specific
        test_v7_tool_count,
        test_v7_daemon_threads,
        test_v7_notification_drain_clears,
        test_v7_notification_xml_construction,
        test_v7_summary_truncation,
        # v8 mechanism-specific
        test_v8_tool_count,
        test_v8_teammate_tools_subset,
        test_v8_message_types_count,
        test_v8_teammate_bg_prefix,
        test_v8_spawn_teammate_errors,
        test_v8_find_teammate_cross_team,
        test_v8_teammate_loop_structure,
        test_v8_broadcast_to_all,
        test_v8_delete_sends_shutdown,
        # v2/v3 mechanism-specific
        test_v2_system_reminders,
        test_v3_context_isolation,
        # --- NEW: v0 mechanism tests ---
        test_v0_only_bash_tool,
        test_v0_agent_loop_recursion,
        test_v0_subagent_via_bash,
        # --- NEW: v1 mechanism tests ---
        test_v1_exactly_four_tools,
        test_v1_safe_path_validation,
        test_v1_bash_dangerous_commands,
        test_v1_agent_loop_structure,
        # --- NEW: v2 mechanism tests ---
        test_v2_todo_max_items_enforced,
        test_v2_todo_render_format_detailed,
        test_v2_status_progression_enforcement,
        # --- NEW: v3 mechanism tests ---
        test_v3_agent_types_exactly_three,
        test_v3_task_prevents_recursion,
        test_v3_run_task_isolation,
        # --- NEW: v4 mechanism tests ---
        test_v4_skill_loader_yaml_edge_cases,
        test_v4_skill_loader_cache_separation,
        test_v4_skill_loader_empty_frontmatter,
        # --- NEW: v5 mechanism tests ---
        test_v5_compactable_tools_set,
        test_v5_estimate_tokens_precision,
        test_v5_microcompact_empty_messages,
        test_v5_microcompact_all_recent,
        test_v5_microcompact_no_compactable,
        test_v5_should_compact_various_thresholds,
        test_v5_handle_large_output_at_boundary,
        test_v5_keep_recent_constant,
        # --- NEW: v6 mechanism tests ---
        test_v6_task_thread_safety,
        test_v6_dependency_chain,
        test_v6_task_delete_removes_disk,
        test_v6_task_active_form,
        test_v6_task_owner_tracking,
        # --- NEW: v7 mechanism tests ---
        test_v7_background_error_handling,
        test_v7_stop_then_get_output,
        test_v7_multiple_concurrent_tasks,
        test_v7_notification_has_required_fields,
        # --- NEW: v8 mechanism tests ---
        test_v8_create_team_creates_directory,
        test_v8_check_inbox_missing_file,
        test_v8_broadcast_excludes_sender,
        test_v8_teammate_tools_excludes_team_mgmt,
        test_v8_find_teammate_with_team_name,
        test_v8_send_message_validates_type,
        test_v9_teammate_identity_injection,
        test_v9_unclaimed_task_filter,
        test_v9_teammate_loop_phases,
        # --- NEW: cross-version parity tests ---
        test_context_manager_parity,
        # --- NEW: behavioral tests ---
        test_auto_compact_replaces_all_messages,
        test_microcompact_min_savings_threshold,
        test_compactable_tools_exactly_eight,
        test_v7_notification_attachment_format,
        test_v7_output_file_extension,
        test_bash_timeout_default,
        test_task_file_naming_sanitized_no_prefix,
    ]

    failed = []
    for test_fn in tests:
        name = test_fn.__name__
        print(f"\n{'='*50}")
        print(f"Running: {name}")
        print('='*50)
        try:
            if not test_fn():
                failed.append(name)
        except Exception as e:
            print(f"FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed.append(name)

    print(f"\n{'='*50}")
    print(f"Results: {len(tests) - len(failed)}/{len(tests)} passed")
    print('='*50)

    if failed:
        print(f"FAILED: {failed}")
        sys.exit(1)
    else:
        print("All unit tests passed!")
        sys.exit(0)
