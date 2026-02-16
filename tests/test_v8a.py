"""
Tests for v8a_team_foundation.py - Team foundation: TeammateManager, create/delete, lifecycle.

v8a introduces teams as persistent agents with identity, but no messaging yet.
No SendMessage, no inbox, no check_inbox -- those come in v8b.

Unit tests verify TeammateManager create/delete, Teammate dataclass,
config.json persistence, TEAMS_DIR, BackgroundManager, and tool count.

LLM integration tests verify the model can use TeamCreate/TeamDelete.
"""
import os
import sys
import tempfile
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.helpers import get_client, run_agent, run_tests, MODEL
from tests.helpers import BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL
from tests.helpers import TASK_CREATE_TOOL, TASK_LIST_TOOL, TASK_UPDATE_TOOL
from tests.helpers import TASK_OUTPUT_TOOL, TASK_STOP_TOOL
from tests.helpers import TEAM_CREATE_TOOL, TEAM_DELETE_TOOL

from pathlib import Path
from v8a_team_foundation import (
    TeammateManager, Teammate, TaskManager,
    TEAMMATE_TOOLS, ALL_TOOLS, TEAMS_DIR,
    BackgroundManager, TEAMMATE_COLORS,
)


# =============================================================================
# Unit Tests - TeammateManager Foundation
# =============================================================================

def test_create_team():
    """Verify TeammateManager.create_team returns success for new team."""
    tm = TeammateManager()
    result = tm.create_team("alpha-team")
    assert "created" in result.lower(), f"Expected 'created' in response, got: {result}"
    print("PASS: test_create_team")
    return True


def test_create_duplicate_team():
    """Verify creating a team with the same name returns 'already exists'."""
    tm = TeammateManager()
    tm.create_team("dup-team")
    result = tm.create_team("dup-team")
    assert "already exists" in result.lower(), f"Expected 'already exists', got: {result}"
    print("PASS: test_create_duplicate_team")
    return True


def test_delete_team():
    """Verify delete_team removes the team and marks teammates as shutdown."""
    tm = TeammateManager()
    tm.create_team("del-team")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    teammate = Teammate(name="worker", team_name="del-team", inbox_path=inbox)
    tm._teams["del-team"]["worker"] = teammate

    result = tm.delete_team("del-team")
    assert "deleted" in result.lower(), f"Expected 'deleted' in response, got: {result}"
    assert "del-team" not in tm._teams, "Team should be removed from _teams"
    assert teammate.status == "shutdown", "Teammate status should be 'shutdown'"

    inbox.unlink(missing_ok=True)
    print("PASS: test_delete_team")
    return True


def test_team_status():
    """Verify get_team_status returns team info."""
    tm = TeammateManager()
    assert "No teams" in tm.get_team_status(), "Empty manager should say 'No teams'"

    tm.create_team("status-team")
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    teammate = Teammate(name="bob", team_name="status-team", inbox_path=inbox)
    tm._teams["status-team"]["bob"] = teammate

    status = tm.get_team_status("status-team")
    assert "status-team" in status, f"Team name should be in status, got: {status}"
    assert "bob" in status, f"Member name should be in status, got: {status}"

    inbox.unlink(missing_ok=True)
    print("PASS: test_team_status")
    return True


def test_teammate_dataclass_defaults():
    """Verify Teammate dataclass defaults: status='active', agent_id auto-generated."""
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    t = Teammate(name="alice", team_name="test-team", inbox_path=inbox)

    assert t.status == "active", f"Initial status should be 'active', got '{t.status}'"
    assert t.agent_id == "alice@test-team", f"Expected 'alice@test-team', got '{t.agent_id}'"
    assert t.name == "alice"
    assert t.team_name == "test-team"

    inbox.unlink(missing_ok=True)
    print("PASS: test_teammate_dataclass_defaults")
    return True


def test_teammate_status_transitions():
    """Verify Teammate status can be changed to idle and shutdown."""
    t = Teammate(name="test", team_name="test-team")
    assert t.status == "active"

    t.status = "idle"
    assert t.status == "idle"

    t.status = "shutdown"
    assert t.status == "shutdown"

    print("PASS: test_teammate_status_transitions")
    return True


def test_config_json_created():
    """Verify create_team creates config.json with correct structure."""
    import v8a_team_foundation
    orig_dir = v8a_team_foundation.TEAMS_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        v8a_team_foundation.TEAMS_DIR = Path(tmpdir)
        tm = TeammateManager()
        tm.create_team("cfg-test")

        config_path = Path(tmpdir) / "cfg-test" / "config.json"
        assert config_path.exists(), "config.json should exist after create_team"
        data = json.loads(config_path.read_text())
        assert data["name"] == "cfg-test"
        assert "members" in data
        assert "leadAgentId" in data

        v8a_team_foundation.TEAMS_DIR = orig_dir
    print("PASS: test_config_json_created")
    return True


def test_config_persists_after_spawn():
    """Verify config.json reflects team membership after _update_team_config."""
    import v8a_team_foundation
    orig_dir = v8a_team_foundation.TEAMS_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        v8a_team_foundation.TEAMS_DIR = Path(tmpdir)
        tm = TeammateManager()
        tm.create_team("persist-test")

        inbox = Path(tempfile.mktemp(suffix=".jsonl"))
        mate = Teammate(name="alice", team_name="persist-test", inbox_path=inbox)
        tm._teams["persist-test"]["alice"] = mate
        tm._update_team_config("persist-test")

        config_path = Path(tmpdir) / "persist-test" / "config.json"
        data = json.loads(config_path.read_text())
        member_names = [m["name"] for m in data.get("members", [])]
        assert "alice" in member_names, \
            f"config.json should list 'alice' as member, got {member_names}"

        inbox.unlink(missing_ok=True)
        v8a_team_foundation.TEAMS_DIR = orig_dir
    print("PASS: test_config_persists_after_spawn")
    return True


def test_teams_dir_defined():
    """Verify TEAMS_DIR is defined and contains 'teams'."""
    assert TEAMS_DIR is not None, "TEAMS_DIR must be defined"
    assert "teams" in str(TEAMS_DIR).lower(), \
        f"TEAMS_DIR should contain 'teams', got: {TEAMS_DIR}"
    print("PASS: test_teams_dir_defined")
    return True


def test_agent_id_format():
    """Verify Teammate agent_id follows '{name}@{team}' format."""
    mate = Teammate(name="alice", team_name="my-team")
    assert mate.agent_id == "alice@my-team", \
        f"Expected 'alice@my-team', got '{mate.agent_id}'"
    print("PASS: test_agent_id_format")
    return True


def test_teammate_colors_cycle():
    """Verify colors cycle through TEAMMATE_COLORS array."""
    tm = TeammateManager()
    tm.create_team("color-test")
    colors_seen = []
    inboxes = []
    for i in range(7):
        inbox = Path(tempfile.mktemp(suffix=".jsonl"))
        color_idx = i % len(TEAMMATE_COLORS)
        mate = Teammate(name=f"w{i}", team_name="color-test", inbox_path=inbox,
                        color=TEAMMATE_COLORS[color_idx])
        tm._teams["color-test"][f"w{i}"] = mate
        colors_seen.append(mate.color)
        inboxes.append(inbox)

    assert colors_seen[0] == colors_seen[5], "Color at index 0 should equal index 5 (cycling)"
    assert colors_seen[1] == colors_seen[6], "Color at index 1 should equal index 6 (cycling)"

    for inbox in inboxes:
        inbox.unlink(missing_ok=True)
    print("PASS: test_teammate_colors_cycle")
    return True


def test_spawn_teammate_error_no_team():
    """Verify spawn_teammate returns error for non-existent team."""
    tm = TeammateManager()
    result = tm.spawn_teammate("worker", "ghost-team", "do stuff")
    assert "error" in result.lower(), \
        f"Should return error for non-existent team, got: {result}"
    print("PASS: test_spawn_teammate_error_no_team")
    return True


def test_spawn_teammate_returns_json():
    """Verify spawn_teammate returns JSON with name, team, status."""
    tm = TeammateManager()
    tm.create_team("spawn-test")
    result = tm.spawn_teammate("w1", "spawn-test", "test prompt")
    data = json.loads(result)
    assert data["name"] == "w1"
    assert data["team"] == "spawn-test"
    assert data["status"] == "active"
    tm.delete_team("spawn-test")
    time.sleep(0.1)
    print("PASS: test_spawn_teammate_returns_json")
    return True


def test_find_teammate_cross_team():
    """Verify _find_teammate searches across all teams when team_name is None."""
    tm = TeammateManager()
    tm.create_team("alpha")
    tm.create_team("beta")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="hidden", team_name="beta", inbox_path=inbox)
    tm._teams["beta"]["hidden"] = mate

    found = tm._find_teammate("hidden")
    assert found is not None, "Should find teammate across teams"
    assert found.team_name == "beta"

    not_found = tm._find_teammate("nonexistent")
    assert not_found is None, "Should not find nonexistent teammate"

    inbox.unlink(missing_ok=True)
    print("PASS: test_find_teammate_cross_team")
    return True


def test_background_manager_teammate_prefix():
    """Verify BackgroundManager maps 'teammate' type to 't' prefix."""
    bm = BackgroundManager()
    tid = bm.run_in_background(lambda: "x", task_type="teammate")
    assert tid.startswith("t"), f"Teammate prefix should be 't', got '{tid[0]}'"
    bm.get_output(tid, block=True, timeout=2000)
    print("PASS: test_background_manager_teammate_prefix")
    return True


def test_v8a_tool_count():
    """Verify v8a has exactly 14 tools (no SendMessage)."""
    # v8a ALL_TOOLS: 4 base + Task + Skill + 4 task CRUD + TaskOutput + TaskStop + TeamCreate + TeamDelete = 14
    assert len(ALL_TOOLS) == 14, f"v8a should have 14 tools, got {len(ALL_TOOLS)}"
    print("PASS: test_v8a_tool_count")
    return True


def test_v8a_no_send_message():
    """Verify v8a does NOT have SendMessage in its tools."""
    all_names = {t["name"] for t in ALL_TOOLS}
    assert "SendMessage" not in all_names, \
        "v8a ALL_TOOLS should NOT include SendMessage (added in v8b)"

    teammate_names = {t["name"] for t in TEAMMATE_TOOLS}
    assert "SendMessage" not in teammate_names, \
        "v8a TEAMMATE_TOOLS should NOT include SendMessage (added in v8b)"
    print("PASS: test_v8a_no_send_message")
    return True


def test_v8a_teammate_tools_have_task_crud():
    """Verify TEAMMATE_TOOLS has base tools + task CRUD."""
    tool_names = {t["name"] for t in TEAMMATE_TOOLS}
    assert "bash" in tool_names
    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "edit_file" in tool_names
    assert "TaskCreate" in tool_names
    assert "TaskGet" in tool_names
    assert "TaskUpdate" in tool_names
    assert "TaskList" in tool_names
    print("PASS: test_v8a_teammate_tools_have_task_crud")
    return True


def test_v8a_teammate_tools_exclude_team_mgmt():
    """Verify TEAMMATE_TOOLS excludes TeamCreate and TeamDelete."""
    tool_names = {t["name"] for t in TEAMMATE_TOOLS}
    assert "TeamCreate" not in tool_names, "Teammates should not have TeamCreate"
    assert "TeamDelete" not in tool_names, "Teammates should not have TeamDelete"
    print("PASS: test_v8a_teammate_tools_exclude_team_mgmt")
    return True


def test_v8a_all_tools_have_team_mgmt():
    """Verify ALL_TOOLS includes TeamCreate and TeamDelete."""
    all_names = {t["name"] for t in ALL_TOOLS}
    assert "TeamCreate" in all_names
    assert "TeamDelete" in all_names
    print("PASS: test_v8a_all_tools_have_team_mgmt")
    return True


def test_task_board_sharing():
    """Verify two TaskManagers on the same dir share tasks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tm1 = TaskManager(Path(tmpdir))
        tm2 = TaskManager(Path(tmpdir))

        tm1.create("Shared task")
        tasks_from_tm2 = tm2.list_all()
        assert len(tasks_from_tm2) == 1
        assert tasks_from_tm2[0].subject == "Shared task"
    print("PASS: test_task_board_sharing")
    return True


def test_teammate_loop_has_tool_loop():
    """Verify _teammate_loop has tool execution and shutdown logic."""
    import inspect
    source = inspect.getsource(TeammateManager._teammate_loop)
    assert "tool_use" in source, "Loop must check for tool_use stop reason"
    assert "shutdown" in source, "Loop must handle shutdown"
    assert "microcompact" in source, "Loop must support context compression"
    print("PASS: test_teammate_loop_has_tool_loop")
    return True


# =============================================================================
# LLM Integration Tests
# =============================================================================

V8A_TOOLS = [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
             TASK_CREATE_TOOL, TASK_LIST_TOOL, TASK_UPDATE_TOOL,
             TASK_OUTPUT_TOOL, TASK_STOP_TOOL,
             TEAM_CREATE_TOOL, TEAM_DELETE_TOOL]


def test_llm_creates_team():
    """LLM uses TeamCreate to set up a new team."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = run_agent(
        client,
        "Create a new team called 'frontend-team' for building the UI. Use the TeamCreate tool.",
        V8A_TOOLS,
        system="You are a team lead. Use TeamCreate to set up teams for collaboration.",
    )

    team_calls = [c for c in calls if c[0] == "TeamCreate"]
    assert len(team_calls) >= 1, \
        f"Model should use TeamCreate, got: {[c[0] for c in calls]}"

    print(f"Tool calls: {len(calls)}, TeamCreate: {len(team_calls)}")
    print("PASS: test_llm_creates_team")
    return True


def test_llm_team_lifecycle():
    """LLM creates and then deletes a team."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = run_agent(
        client,
        "Do the following in order:\n"
        "1) Create a team called 'temp-team' using TeamCreate\n"
        "2) Delete the team using TeamDelete\n"
        "Execute both steps.",
        V8A_TOOLS,
        system="You are a team lead. Use TeamCreate and TeamDelete.",
        max_turns=10,
    )

    tool_names = [c[0] for c in calls]
    assert "TeamCreate" in tool_names, f"Should use TeamCreate, got: {tool_names}"
    assert "TeamDelete" in tool_names, f"Should use TeamDelete, got: {tool_names}"

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_llm_team_lifecycle")
    return True


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    sys.exit(0 if run_tests([
        test_create_team,
        test_create_duplicate_team,
        test_delete_team,
        test_team_status,
        test_teammate_dataclass_defaults,
        test_teammate_status_transitions,
        test_config_json_created,
        test_config_persists_after_spawn,
        test_teams_dir_defined,
        test_agent_id_format,
        test_teammate_colors_cycle,
        test_spawn_teammate_error_no_team,
        test_spawn_teammate_returns_json,
        test_find_teammate_cross_team,
        test_background_manager_teammate_prefix,
        test_v8a_tool_count,
        test_v8a_no_send_message,
        test_v8a_teammate_tools_have_task_crud,
        test_v8a_teammate_tools_exclude_team_mgmt,
        test_v8a_all_tools_have_team_mgmt,
        test_task_board_sharing,
        test_teammate_loop_has_tool_loop,
        # LLM integration
        test_llm_creates_team,
        test_llm_team_lifecycle,
    ]) else 1)
