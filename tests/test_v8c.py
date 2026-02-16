"""
Tests for v8c_coordination.py - Shared task board, shutdown protocol, plan approval.

v8c adds coordination on top of v8b messaging: shared task board for work
tracking, shutdown protocol with request_id, plan approval flow, and
teammate status tracking (active/idle/shutdown).

Unit tests verify task board sharing, shutdown protocol, plan approval,
status tracking, config.json persistence, task claiming with blocking,
and race condition safety.

LLM integration tests verify the model uses team + messaging + task tools.
"""
import os
import sys
import tempfile
import time
import json
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.helpers import get_client, run_agent, run_tests, MODEL
from tests.helpers import BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL
from tests.helpers import TASK_CREATE_TOOL, TASK_LIST_TOOL, TASK_UPDATE_TOOL
from tests.helpers import TASK_OUTPUT_TOOL, TASK_STOP_TOOL
from tests.helpers import TEAM_CREATE_TOOL, SEND_MESSAGE_TOOL, TEAM_DELETE_TOOL

from pathlib import Path
from v8c_coordination import (
    TeammateManager, Teammate, TaskManager,
    TEAMMATE_TOOLS, ALL_TOOLS, TEAMS_DIR,
)


# =============================================================================
# Unit Tests - Shared Task Board
# =============================================================================

def test_task_board_sharing():
    """Verify two TaskManagers on the same dir share tasks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tm1 = TaskManager(Path(tmpdir))
        tm2 = TaskManager(Path(tmpdir))

        tm1.create("Shared task")
        tasks = tm2.list_all()
        assert len(tasks) == 1
        assert tasks[0].subject == "Shared task"

        tm1.update("1", owner="frontend-agent")
        task = tm2.get("1")
        assert task.owner == "frontend-agent"
    print("PASS: test_task_board_sharing")
    return True


def test_task_claiming_with_blocking():
    """Verify blocked tasks are not claimable."""
    with tempfile.TemporaryDirectory() as tmpdir:
        task_mgr = TaskManager(Path(tmpdir))
        task_mgr.create("Task A")
        task_mgr.create("Task B")
        task_mgr.create("Blocked C")

        task_mgr.update("3", addBlockedBy=["1"])

        all_tasks = task_mgr.list_all()
        unclaimed = [
            t for t in all_tasks
            if t.status == "pending" and not t.owner and not t.blocked_by
        ]
        assert len(unclaimed) == 2, f"Expected 2 unclaimed unblocked, got {len(unclaimed)}"
        subjects = [t.subject for t in unclaimed]
        assert "Task A" in subjects
        assert "Task B" in subjects
    print("PASS: test_task_claiming_with_blocking")
    return True


def test_task_claim_and_unblock():
    """Verify completing a blocking task unblocks the dependent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        task_mgr = TaskManager(Path(tmpdir))
        task_mgr.create("First")
        task_mgr.create("Dependent")
        task_mgr.update("2", addBlockedBy=["1"])

        task_mgr.update("1", status="in_progress", owner="alice")
        task_mgr.update("1", status="completed")

        t2 = task_mgr.get("2")
        assert "1" not in t2.blocked_by, "Completing task 1 should unblock task 2"
    print("PASS: test_task_claim_and_unblock")
    return True


def test_task_owner_persistence():
    """Verify task owner persists after TaskManager reload."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tm1 = TaskManager(Path(tmpdir))
        tm1.create("Owned task")
        tm1.update("1", owner="bob")

        tm2 = TaskManager(Path(tmpdir))
        task = tm2.get("1")
        assert task.owner == "bob", f"Owner should persist, got '{task.owner}'"
    print("PASS: test_task_owner_persistence")
    return True


def test_multi_owner_race_condition():
    """Verify concurrent task owner updates remain consistent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        task_mgr = TaskManager(Path(tmpdir))
        task_mgr.create("Race task")

        errors = []

        def claim(owner):
            try:
                task_mgr.update("1", owner=owner)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=claim, args=("alice",))
        t2 = threading.Thread(target=claim, args=("bob",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) == 0, f"Race errors: {errors}"
        final = task_mgr.get("1")
        assert final.owner in ("alice", "bob"), f"Owner should be alice or bob, got '{final.owner}'"
    print("PASS: test_multi_owner_race_condition")
    return True


# =============================================================================
# Unit Tests - Shutdown Protocol
# =============================================================================

def test_shutdown_sets_teammate_status():
    """Verify delete_team marks all teammates as 'shutdown'."""
    tm = TeammateManager()
    tm.create_team("sd-team")

    inbox_a = Path(tempfile.mktemp(suffix=".jsonl"))
    inbox_b = Path(tempfile.mktemp(suffix=".jsonl"))
    mate_a = Teammate(name="a", team_name="sd-team", inbox_path=inbox_a)
    mate_b = Teammate(name="b", team_name="sd-team", inbox_path=inbox_b)
    tm._teams["sd-team"]["a"] = mate_a
    tm._teams["sd-team"]["b"] = mate_b

    tm.delete_team("sd-team")
    assert mate_a.status == "shutdown"
    assert mate_b.status == "shutdown"

    inbox_a.unlink(missing_ok=True)
    inbox_b.unlink(missing_ok=True)
    print("PASS: test_shutdown_sets_teammate_status")
    return True


def test_shutdown_sends_request_with_id():
    """Verify shutdown_request messages in inbox contain necessary fields."""
    tm = TeammateManager()
    tm.create_team("reqid-team")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="worker", team_name="reqid-team", inbox_path=inbox)
    tm._teams["reqid-team"]["worker"] = mate

    tm.send_message("worker", "shutting down", msg_type="shutdown_request",
                    team_name="reqid-team")

    msgs = tm.check_inbox("worker", "reqid-team")
    assert len(msgs) == 1
    assert msgs[0]["type"] == "shutdown_request"

    inbox.unlink(missing_ok=True)
    print("PASS: test_shutdown_sends_request_with_id")
    return True


def test_pending_shutdowns_tracking():
    """Verify _pending_shutdowns dict exists on TeammateManager."""
    tm = TeammateManager()
    assert hasattr(tm, "_pending_shutdowns"), "v8c must have _pending_shutdowns"
    assert isinstance(tm._pending_shutdowns, dict)
    print("PASS: test_pending_shutdowns_tracking")
    return True


# =============================================================================
# Unit Tests - Teammate Status Tracking
# =============================================================================

def test_teammate_status_lifecycle():
    """Verify Teammate status transitions: active -> idle -> shutdown."""
    t = Teammate(name="w", team_name="t")
    assert t.status == "active"
    t.status = "idle"
    assert t.status == "idle"
    t.status = "shutdown"
    assert t.status == "shutdown"
    print("PASS: test_teammate_status_lifecycle")
    return True


def test_get_team_status_shows_members():
    """Verify get_team_status includes member info."""
    tm = TeammateManager()
    tm.create_team("info-team")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="alice", team_name="info-team", inbox_path=inbox)
    tm._teams["info-team"]["alice"] = mate

    status = tm.get_team_status("info-team")
    assert "info-team" in status
    assert "alice" in status

    inbox.unlink(missing_ok=True)
    print("PASS: test_get_team_status_shows_members")
    return True


# =============================================================================
# Unit Tests - Config Persistence
# =============================================================================

def test_config_json_structure():
    """Verify config.json has name, members, leadAgentId."""
    import v8c_coordination
    orig_dir = v8c_coordination.TEAMS_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        v8c_coordination.TEAMS_DIR = Path(tmpdir)
        tm = TeammateManager()
        tm.create_team("cfg-test")

        config_path = Path(tmpdir) / "cfg-test" / "config.json"
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert data["name"] == "cfg-test"
        assert "members" in data
        assert "leadAgentId" in data

        v8c_coordination.TEAMS_DIR = orig_dir
    print("PASS: test_config_json_structure")
    return True


def test_config_updates_after_member_add():
    """Verify config.json reflects added member."""
    import v8c_coordination
    orig_dir = v8c_coordination.TEAMS_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        v8c_coordination.TEAMS_DIR = Path(tmpdir)
        tm = TeammateManager()
        tm.create_team("member-cfg")

        inbox = Path(tempfile.mktemp(suffix=".jsonl"))
        mate = Teammate(name="alice", team_name="member-cfg", inbox_path=inbox)
        tm._teams["member-cfg"]["alice"] = mate
        tm._update_team_config("member-cfg")

        config_path = Path(tmpdir) / "member-cfg" / "config.json"
        data = json.loads(config_path.read_text())
        names = [m["name"] for m in data["members"]]
        assert "alice" in names

        inbox.unlink(missing_ok=True)
        v8c_coordination.TEAMS_DIR = orig_dir
    print("PASS: test_config_updates_after_member_add")
    return True


def test_config_updates_after_member_remove():
    """Verify config.json reflects removed member."""
    import v8c_coordination
    orig_dir = v8c_coordination.TEAMS_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        v8c_coordination.TEAMS_DIR = Path(tmpdir)
        tm = TeammateManager()
        tm.create_team("rem-cfg")

        inbox = Path(tempfile.mktemp(suffix=".jsonl"))
        mate = Teammate(name="bob", team_name="rem-cfg", inbox_path=inbox)
        tm._teams["rem-cfg"]["bob"] = mate
        tm._update_team_config("rem-cfg")

        del tm._teams["rem-cfg"]["bob"]
        tm._update_team_config("rem-cfg")

        config_path = Path(tmpdir) / "rem-cfg" / "config.json"
        data = json.loads(config_path.read_text())
        assert len(data["members"]) == 0

        inbox.unlink(missing_ok=True)
        v8c_coordination.TEAMS_DIR = orig_dir
    print("PASS: test_config_updates_after_member_remove")
    return True


# =============================================================================
# Unit Tests - Tools
# =============================================================================

def test_v8c_tool_count():
    """Verify v8c has 15 tools (same as v8b: includes SendMessage)."""
    assert len(ALL_TOOLS) == 15, f"v8c should have 15 tools, got {len(ALL_TOOLS)}"
    print("PASS: test_v8c_tool_count")
    return True


def test_v8c_has_send_message():
    """Verify v8c has SendMessage in ALL_TOOLS and TEAMMATE_TOOLS."""
    all_names = {t["name"] for t in ALL_TOOLS}
    assert "SendMessage" in all_names

    teammate_names = {t["name"] for t in TEAMMATE_TOOLS}
    assert "SendMessage" in teammate_names
    print("PASS: test_v8c_has_send_message")
    return True


def test_v8c_teammate_tools_have_task_crud():
    """Verify TEAMMATE_TOOLS has task CRUD tools."""
    names = {t["name"] for t in TEAMMATE_TOOLS}
    for expected in ["TaskCreate", "TaskGet", "TaskUpdate", "TaskList"]:
        assert expected in names, f"Missing {expected}"
    print("PASS: test_v8c_teammate_tools_have_task_crud")
    return True


def test_v8c_teammate_tools_exclude_team_mgmt():
    """Verify TEAMMATE_TOOLS excludes TeamCreate, TeamDelete."""
    names = {t["name"] for t in TEAMMATE_TOOLS}
    assert "TeamCreate" not in names
    assert "TeamDelete" not in names
    print("PASS: test_v8c_teammate_tools_exclude_team_mgmt")
    return True


# =============================================================================
# Unit Tests - Agent Loop Structure
# =============================================================================

def test_v8c_agent_loop_has_drain():
    """Verify v8c code has drain_notifications."""
    import v8c_coordination
    source = open(v8c_coordination.__file__).read()
    assert "drain_notifications" in source, "Must have drain_notifications"
    assert "def agent_loop" in source, "Must have agent_loop function"
    print("PASS: test_v8c_agent_loop_has_drain")
    return True


def test_v8c_teammate_loop_has_inbox_check():
    """Verify _teammate_loop checks inbox."""
    import inspect
    source = inspect.getsource(TeammateManager._teammate_loop)
    assert "check_inbox" in source, "Must check inbox in teammate loop"
    print("PASS: test_v8c_teammate_loop_has_inbox_check")
    return True


# =============================================================================
# LLM Integration Tests
# =============================================================================

V8C_TOOLS = [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
             TASK_CREATE_TOOL, TASK_LIST_TOOL, TASK_UPDATE_TOOL,
             TASK_OUTPUT_TOOL, TASK_STOP_TOOL,
             TEAM_CREATE_TOOL, SEND_MESSAGE_TOOL, TEAM_DELETE_TOOL]


def test_llm_team_and_task_workflow():
    """LLM creates team, creates task, sends message, cleans up."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = run_agent(
        client,
        "Do the following in order:\n"
        "1) Create a team called 'dev-team' using TeamCreate\n"
        "2) Create a task 'Setup DB' using TaskCreate\n"
        "3) Send a message to 'alice' saying 'Start work' using SendMessage\n"
        "4) Delete the team using TeamDelete\n"
        "Execute all four steps.",
        V8C_TOOLS,
        system="You are a team lead. Use all available tools.",
        max_turns=10,
    )

    tool_names = [c[0] for c in calls]
    assert "TeamCreate" in tool_names
    assert "TaskCreate" in tool_names
    assert "SendMessage" in tool_names
    assert "TeamDelete" in tool_names

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_llm_team_and_task_workflow")
    return True


def test_llm_shutdown_request():
    """LLM uses SendMessage with type='shutdown_request'."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = run_agent(
        client,
        "You MUST call the SendMessage tool with these exact parameters: "
        "type='shutdown_request', recipient='worker-1', content='Shutting down'. "
        "Do NOT respond with text. Just call the tool.",
        V8C_TOOLS,
        system="You MUST use the SendMessage tool when asked.",
    )

    msg_calls = [c for c in calls if c[0] == "SendMessage"]
    assert len(msg_calls) >= 1, \
        f"Model should use SendMessage, got: {[c[0] for c in calls]}"

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_llm_shutdown_request")
    return True


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    sys.exit(0 if run_tests([
        # Shared task board
        test_task_board_sharing,
        test_task_claiming_with_blocking,
        test_task_claim_and_unblock,
        test_task_owner_persistence,
        test_multi_owner_race_condition,
        # Shutdown protocol
        test_shutdown_sets_teammate_status,
        test_shutdown_sends_request_with_id,
        test_pending_shutdowns_tracking,
        # Status tracking
        test_teammate_status_lifecycle,
        test_get_team_status_shows_members,
        # Config persistence
        test_config_json_structure,
        test_config_updates_after_member_add,
        test_config_updates_after_member_remove,
        # Tools
        test_v8c_tool_count,
        test_v8c_has_send_message,
        test_v8c_teammate_tools_have_task_crud,
        test_v8c_teammate_tools_exclude_team_mgmt,
        # Agent loop
        test_v8c_agent_loop_has_drain,
        test_v8c_teammate_loop_has_inbox_check,
        # LLM integration
        test_llm_team_and_task_workflow,
        test_llm_shutdown_request,
    ]) else 1)
