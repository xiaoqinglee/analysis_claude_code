"""
Tests for v9_autonomous_agent.py - Autonomous teams with idle cycle.

v9 extends v8 with three autonomy features:
  - Idle cycle: teammates poll for new work after finishing
  - Auto-claiming: unclaimed pending tasks are picked up automatically
  - Identity injection: re-inject name/team after context compression

Unit tests verify the structural differences from v8.
LLM integration tests verify the model can use team + task tools together.
"""
import os
import sys
import tempfile
import time
import json
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.helpers import get_client, run_agent, run_tests, MODEL
from tests.helpers import BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL
from tests.helpers import TASK_CREATE_TOOL, TASK_LIST_TOOL, TASK_UPDATE_TOOL
from tests.helpers import TASK_OUTPUT_TOOL, TASK_STOP_TOOL
from tests.helpers import TEAM_CREATE_TOOL, SEND_MESSAGE_TOOL, TEAM_DELETE_TOOL

from pathlib import Path
from v9_autonomous_agent import TeammateManager, Teammate, TaskManager


# =============================================================================
# Unit Tests - v9 Autonomous Teammate Loop
# =============================================================================

def test_v9_teammate_loop_has_idle_phase():
    """Verify _idle_phase contains the idle polling logic."""
    source = inspect.getsource(TeammateManager._idle_phase)

    assert "idle" in source, "Must set teammate status to 'idle'"
    assert "check_inbox" in source, "Idle phase must check teammate inbox"
    assert "IDLE_POLL_INTERVAL" in source, \
        "Idle phase should use IDLE_POLL_INTERVAL constant"
    assert "IDLE_TIMEOUT" in source, "Idle phase should use IDLE_TIMEOUT constant"

    print("PASS: test_v9_teammate_loop_has_idle_phase")
    return True


def test_v9_teammate_loop_auto_claiming():
    """Verify _scan_unclaimed_tasks auto-claims unclaimed, unblocked pending tasks."""
    source = inspect.getsource(TeammateManager._scan_unclaimed_tasks)

    assert "pending" in source, "Must filter for pending status"
    assert "owner" in source, "Must check owner is empty"
    assert "blocked_by" in source, "Must check blocked_by is empty"

    # Also check that _claim_task sets in_progress
    claim_source = inspect.getsource(TeammateManager._claim_task)
    assert "in_progress" in claim_source, \
        "Must set claimed task to in_progress"

    print("PASS: test_v9_teammate_loop_auto_claiming")
    return True


def test_v9_teammate_loop_identity_injection():
    """Verify _teammate_loop re-injects identity after auto_compact."""
    source = inspect.getsource(TeammateManager._teammate_loop)

    assert "auto_compact" in source, "Loop must call auto_compact"
    assert "Remember" in source or "identity" in source.lower(), \
        "Loop must re-inject identity after compression"
    assert "teammate.name" in source, "Identity injection must include name"
    assert "teammate.team_name" in source, \
        "Identity injection must include team name"

    print("PASS: test_v9_teammate_loop_identity_injection")
    return True


def test_v9_teammate_loop_shutdown_on_request():
    """Verify _handle_inbox_messages handles shutdown_request messages."""
    source = inspect.getsource(TeammateManager._handle_inbox_messages)

    assert "shutdown_request" in source, \
        "Must detect shutdown_request messages"
    assert "shutdown" in source, "Must set status to shutdown"

    print("PASS: test_v9_teammate_loop_shutdown_on_request")
    return True


def test_v9_teammate_loop_context_compression():
    """Verify _teammate_loop supports all 3 compression layers."""
    source = inspect.getsource(TeammateManager._teammate_loop)

    assert "microcompact" in source, "Must use microcompact"
    assert "should_compact" in source, "Must use should_compact"
    assert "auto_compact" in source, "Must use auto_compact"

    print("PASS: test_v9_teammate_loop_context_compression")
    return True


def test_v9_inherits_v8_messaging():
    """Verify v9 TeammateManager has the same messaging API as v8."""
    tm = TeammateManager()

    assert hasattr(tm, "create_team"), "Must have create_team"
    assert hasattr(tm, "send_message"), "Must have send_message"
    assert hasattr(tm, "check_inbox"), "Must have check_inbox"
    assert hasattr(tm, "delete_team"), "Must have delete_team"
    assert hasattr(tm, "spawn_teammate"), "Must have spawn_teammate"
    assert hasattr(tm, "get_team_status"), "Must have get_team_status"
    assert hasattr(tm, "_find_teammate"), "Must have _find_teammate"

    print("PASS: test_v9_inherits_v8_messaging")
    return True


def test_v9_message_types_complete():
    """Verify MESSAGE_TYPES includes all 5 required types."""
    expected = {"message", "broadcast", "shutdown_request",
                "shutdown_response", "plan_approval_response"}
    assert TeammateManager.MESSAGE_TYPES == expected, \
        f"MESSAGE_TYPES should be {expected}, got {TeammateManager.MESSAGE_TYPES}"

    print("PASS: test_v9_message_types_complete")
    return True


def test_v9_teammate_tools_exclude_team_mgmt():
    """Verify TEAMMATE_TOOLS excludes TeamCreate and TeamDelete."""
    from v9_autonomous_agent import TEAMMATE_TOOLS
    tool_names = {t["name"] for t in TEAMMATE_TOOLS}
    assert "TeamCreate" not in tool_names, "Teammates should not have TeamCreate"
    assert "TeamDelete" not in tool_names, "Teammates should not have TeamDelete"
    assert "SendMessage" in tool_names, "Teammates should have SendMessage"
    assert "TaskCreate" in tool_names, "Teammates should have TaskCreate"

    print("PASS: test_v9_teammate_tools_exclude_team_mgmt")
    return True


def test_v9_all_tools_count():
    """Verify v9 ALL_TOOLS has the same count as v8 (15 tools)."""
    from v9_autonomous_agent import ALL_TOOLS
    assert len(ALL_TOOLS) == 15, f"v9 should have 15 tools, got {len(ALL_TOOLS)}"

    print("PASS: test_v9_all_tools_count")
    return True


def test_v9_idle_loop_unclaimed_filter():
    """Verify the unclaimed task filter checks: pending + no owner + no blocked_by."""
    source = inspect.getsource(TeammateManager._scan_unclaimed_tasks)

    assert "pending" in source, "Must filter for pending status"
    assert "owner" in source, "Must check owner is empty"
    assert "blocked_by" in source, "Must check blocked_by is empty"

    print("PASS: test_v9_idle_loop_unclaimed_filter")
    return True


def test_v9_broadcast_excludes_sender():
    """Verify broadcast sends to N-1 teammates (excludes the sender)."""
    tm = TeammateManager()
    tm.create_team("v9-excl-test")

    inboxes = []
    for name in ["sender", "recv1", "recv2"]:
        inbox = Path(tempfile.mktemp(suffix=".jsonl"))
        mate = Teammate(name=name, team_name="v9-excl-test", inbox_path=inbox)
        tm._teams["v9-excl-test"][name] = mate
        inboxes.append(inbox)

    tm.send_message("", "Hello all", msg_type="broadcast",
                     sender="sender", team_name="v9-excl-test")

    sender_msgs = tm.check_inbox("sender", "v9-excl-test")
    assert len(sender_msgs) == 0, "Sender should not receive own broadcast"

    for name in ["recv1", "recv2"]:
        msgs = tm.check_inbox(name, "v9-excl-test")
        assert len(msgs) == 1, f"{name} should have received 1 broadcast"

    for inbox in inboxes:
        inbox.unlink(missing_ok=True)

    print("PASS: test_v9_broadcast_excludes_sender")
    return True


def test_v9_task_manager_thread_safety():
    """Verify TaskManager create is thread-safe with concurrent creates."""
    import threading

    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        errors = []
        ids_created = []

        def create_tasks(start, count):
            try:
                for i in range(count):
                    t = tm.create(f"Thread-{start}-{i}")
                    ids_created.append(t.id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_tasks, args=(i, 5)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"
        assert len(set(ids_created)) == 20, \
            f"Expected 20 unique IDs, got {len(set(ids_created))}"

    print("PASS: test_v9_task_manager_thread_safety")
    return True


def test_v9_dependency_chain():
    """Verify dependency chain A->B->C: completing A unblocks B but not C."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(Path(tmpdir))
        tm.create("Task A")
        tm.create("Task B")
        tm.create("Task C")

        tm.update("2", addBlockedBy=["1"])
        tm.update("3", addBlockedBy=["2"])

        tm.update("1", status="completed")

        b = tm.get("2")
        assert "1" not in b.blocked_by, "Completing A should unblock B"

        c = tm.get("3")
        assert "2" in c.blocked_by, "C should still be blocked by B"

    print("PASS: test_v9_dependency_chain")
    return True


def test_v9_vs_v8c_loop_difference():
    """Verify v9 has idle phase and identity re-injection that v8c does not."""
    from v8c_coordination import TeammateManager as V8CTM

    v8c_source = inspect.getsource(V8CTM._teammate_loop)
    v9_loop_source = inspect.getsource(TeammateManager._teammate_loop)
    v9_idle_source = inspect.getsource(TeammateManager._idle_phase)

    # v8c never has idle_phase, v9 does
    assert "_idle_phase" not in v8c_source, \
        "v8c should NOT call _idle_phase"
    assert "_idle_phase" in v9_loop_source or "idle" in v9_loop_source, \
        "v9 MUST reference idle phase"

    # v9's _idle_phase sets status to "idle"
    assert '"idle"' in v9_idle_source, "v9 _idle_phase MUST set status to 'idle'"

    # v9 has identity re-injection, v8c does not
    v8c_has_reinject = "_reinject_identity" in v8c_source
    v9_has_reinject = "_reinject_identity" in v9_loop_source
    assert not v8c_has_reinject, "v8c should NOT have identity re-injection"
    assert v9_has_reinject, "v9 MUST have identity re-injection"

    print("PASS: test_v9_vs_v8c_loop_difference")
    return True


def test_v9_system_prompt_mentions_autonomous():
    """Verify v9 system prompt mentions autonomous behavior."""
    from v9_autonomous_agent import SYSTEM
    assert "autonomous" in SYSTEM.lower() or "auto-claim" in SYSTEM.lower() or \
           "idle" in SYSTEM.lower(), \
        "v9 system prompt should mention autonomous/auto-claim/idle behavior"

    print("PASS: test_v9_system_prompt_mentions_autonomous")
    return True


def test_idle_poll_interval_default():
    """Verify IDLE_POLL_INTERVAL matches cli.js cZz=1000ms (1 second)."""
    from v9_autonomous_agent import IDLE_POLL_INTERVAL
    assert IDLE_POLL_INTERVAL == 1, f"Expected 1s, got {IDLE_POLL_INTERVAL}s"
    print("PASS: test_idle_poll_interval_default")
    return True


# =============================================================================
# v9 New Mechanism Tests (from final_design.md)
# =============================================================================


def test_idle_cycle_message_wake():
    """Verify _idle_phase returns 'resume' when inbox messages arrive."""
    from v9_autonomous_agent import TeammateManager, Teammate, IDLE_REASONS
    tm = TeammateManager()
    tm.create_team("idle-msg-test")
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="idler", team_name="idle-msg-test", inbox_path=inbox)
    tm._teams["idle-msg-test"]["idler"] = mate

    # Send a message before starting idle phase
    tm.send_message("idler", "Wake up!", msg_type="message",
                    sender="lead", team_name="idle-msg-test")

    sub_messages = [{"role": "user", "content": "initial"}]
    result = tm._idle_phase(mate, sub_messages)
    assert result == "resume", f"Expected 'resume' on message wake, got '{result}'"
    inbox.unlink(missing_ok=True)
    print("PASS: test_idle_cycle_message_wake")
    return True


def test_idle_cycle_task_wake():
    """Verify _idle_phase returns 'resume' when unclaimed task appears."""
    from v9_autonomous_agent import TeammateManager, Teammate, TASK_MGR
    tm = TeammateManager()
    tm.create_team("idle-task-test")
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="claimer", team_name="idle-task-test", inbox_path=inbox)
    tm._teams["idle-task-test"]["claimer"] = mate

    # Create an unclaimed task
    TASK_MGR.create("Unclaimed task for idle wake")

    sub_messages = [{"role": "user", "content": "initial"}]
    result = tm._idle_phase(mate, sub_messages)
    assert result == "resume", f"Expected 'resume' on task claim, got '{result}'"
    inbox.unlink(missing_ok=True)
    print("PASS: test_idle_cycle_task_wake")
    return True


def test_idle_cycle_timeout():
    """Verify _idle_phase returns 'timeout' after IDLE_TIMEOUT with no work."""
    import v9_autonomous_agent
    from v9_autonomous_agent import TeammateManager, Teammate

    tm = TeammateManager()
    tm.create_team("idle-timeout-test")
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="patient", team_name="idle-timeout-test", inbox_path=inbox)
    tm._teams["idle-timeout-test"]["patient"] = mate

    # Shorten timeout for testing
    orig_timeout = v9_autonomous_agent.IDLE_TIMEOUT
    orig_interval = v9_autonomous_agent.IDLE_POLL_INTERVAL
    v9_autonomous_agent.IDLE_TIMEOUT = 1
    v9_autonomous_agent.IDLE_POLL_INTERVAL = 1

    sub_messages = [{"role": "user", "content": "initial"}]
    result = tm._idle_phase(mate, sub_messages)
    assert result == "timeout", f"Expected 'timeout', got '{result}'"

    v9_autonomous_agent.IDLE_TIMEOUT = orig_timeout
    v9_autonomous_agent.IDLE_POLL_INTERVAL = orig_interval
    inbox.unlink(missing_ok=True)
    print("PASS: test_idle_cycle_timeout")
    return True


def test_auto_claim_filters_blocked():
    """Create blocked task, verify _scan_unclaimed_tasks does not claim it."""
    from v9_autonomous_agent import TeammateManager, Teammate, TASK_MGR
    tm = TeammateManager()
    tm.create_team("block-filter-test")
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="scanner", team_name="block-filter-test", inbox_path=inbox)
    tm._teams["block-filter-test"]["scanner"] = mate

    t1 = TASK_MGR.create("Blocker")
    t2 = TASK_MGR.create("Blocked task")
    TASK_MGR.update(t2.id, addBlockedBy=[t1.id])

    sub_messages = [{"role": "user", "content": "scan"}]
    # _scan_unclaimed_tasks should NOT claim blocked task
    claimed = tm._scan_unclaimed_tasks(mate, sub_messages)
    # It may claim t1 (unblocked), but should not claim t2
    t2_refreshed = TASK_MGR.get(t2.id)
    assert t2_refreshed.owner != "scanner", \
        "Blocked task should not be claimed"
    inbox.unlink(missing_ok=True)
    print("PASS: test_auto_claim_filters_blocked")
    return True


def test_auto_claim_filters_owned():
    """Create owned task, verify _scan_unclaimed_tasks does not claim it."""
    from v9_autonomous_agent import TeammateManager, Teammate, TASK_MGR
    tm = TeammateManager()
    tm.create_team("own-filter-test")
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="scanner2", team_name="own-filter-test", inbox_path=inbox)
    tm._teams["own-filter-test"]["scanner2"] = mate

    t = TASK_MGR.create("Already owned")
    TASK_MGR.update(t.id, owner="someone-else")

    sub_messages = [{"role": "user", "content": "scan"}]
    claimed = tm._scan_unclaimed_tasks(mate, sub_messages)
    t_refreshed = TASK_MGR.get(t.id)
    assert t_refreshed.owner == "someone-else", \
        "Already-owned task should keep its owner"
    inbox.unlink(missing_ok=True)
    print("PASS: test_auto_claim_filters_owned")
    return True


def test_identity_reinjection():
    """Simulate auto_compact, verify identity string prepended."""
    from v9_autonomous_agent import TeammateManager, Teammate
    mate = Teammate(name="bob", team_name="alpha", agent_id="bob@alpha")
    sub_messages = [{"role": "user", "content": "Work on task X."}]
    TeammateManager._reinject_identity(mate, sub_messages)
    assert "bob" in sub_messages[0]["content"], \
        "Identity re-injection should include teammate name"
    assert "alpha" in sub_messages[0]["content"], \
        "Identity re-injection should include team name"
    assert "bob@alpha" in sub_messages[0]["content"], \
        "Identity re-injection should include agent_id"
    print("PASS: test_identity_reinjection")
    return True


def test_plan_approval_approve():
    """Send plan_approval_response with approve, verify teammate resumes."""
    from v9_autonomous_agent import TeammateManager, Teammate
    tm = TeammateManager()
    tm.create_team("plan-test")
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="planner", team_name="plan-test", inbox_path=inbox)
    tm._teams["plan-test"]["planner"] = mate

    # Simulate plan approval response
    msg = {"type": "plan_approval_response", "approved": True, "content": ""}
    sub_messages = [{"role": "user", "content": "initial"}]
    result = tm._handle_inbox_messages(mate, [msg], sub_messages)
    assert result is None, "Approval should not trigger shutdown"
    # Should have injected a user message about approval
    assert any("APPROVED" in str(m.get("content", "")) for m in sub_messages), \
        "Approved plan should inject APPROVED text into conversation"
    inbox.unlink(missing_ok=True)
    print("PASS: test_plan_approval_approve")
    return True


def test_plan_approval_reject():
    """Send plan_approval_response with reject+feedback, verify feedback injected."""
    from v9_autonomous_agent import TeammateManager, Teammate
    tm = TeammateManager()
    tm.create_team("plan-reject-test")
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="planner2", team_name="plan-reject-test", inbox_path=inbox)
    tm._teams["plan-reject-test"]["planner2"] = mate

    msg = {"type": "plan_approval_response", "approved": False, "content": "Add error handling"}
    sub_messages = [{"role": "user", "content": "initial"}]
    result = tm._handle_inbox_messages(mate, [msg], sub_messages)
    assert result is None, "Rejection should not trigger shutdown"
    assert any("REJECTED" in str(m.get("content", "")) or
               "Add error handling" in str(m.get("content", ""))
               for m in sub_messages), \
        "Rejected plan should inject feedback text"
    inbox.unlink(missing_ok=True)
    print("PASS: test_plan_approval_reject")
    return True


def test_idle_reasons():
    """Verify all idle reasons are tracked correctly."""
    from v9_autonomous_agent import IDLE_REASONS
    expected_keys = {"no_tool_use", "awaiting_messages", "awaiting_tasks", "timeout"}
    assert set(IDLE_REASONS.keys()) == expected_keys, \
        f"Expected keys {expected_keys}, got {set(IDLE_REASONS.keys())}"
    for key, value in IDLE_REASONS.items():
        assert isinstance(value, str) and len(value) > 0, \
            f"IDLE_REASONS['{key}'] should be a non-empty string"
    print("PASS: test_idle_reasons")
    return True


def test_plan_approval_end_to_end():
    """Write plan_approval_response message to inbox, call check_inbox, verify processing."""
    from v9_autonomous_agent import TeammateManager, Teammate
    tm = TeammateManager()
    tm.create_team("plan-e2e-test")
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="planner-e2e", team_name="plan-e2e-test", inbox_path=inbox)
    tm._teams["plan-e2e-test"]["planner-e2e"] = mate

    # Write a plan_approval_response directly to the inbox file
    msg = json.dumps({"type": "plan_approval_response", "approved": True,
                      "content": "Looks good!", "sender": "lead"})
    with open(inbox, "w") as f:
        f.write(msg + "\n")

    # Read it via check_inbox
    messages = tm.check_inbox("planner-e2e", "plan-e2e-test")
    assert len(messages) == 1, f"Expected 1 message, got {len(messages)}"
    assert messages[0]["type"] == "plan_approval_response", \
        f"Expected plan_approval_response, got {messages[0]['type']}"
    assert messages[0]["approved"] is True, "Expected approved=True"

    # Process via _handle_inbox_messages
    sub_messages = [{"role": "user", "content": "initial"}]
    result = tm._handle_inbox_messages(mate, messages, sub_messages)
    assert result is None, "Approval should not trigger shutdown"
    assert any("APPROVED" in str(m.get("content", "")) for m in sub_messages), \
        "Approved plan should inject APPROVED text into conversation"

    inbox.unlink(missing_ok=True)
    print("PASS: test_plan_approval_end_to_end")
    return True


def test_idle_phase_returns_timeout_on_empty():
    """Call _idle_phase with no inbox messages and no unclaimed tasks, verify timeout."""
    import v9_autonomous_agent
    from v9_autonomous_agent import TeammateManager, Teammate

    tm = TeammateManager()
    tm.create_team("idle-empty-test")
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="empty-idler", team_name="idle-empty-test", inbox_path=inbox)
    tm._teams["idle-empty-test"]["empty-idler"] = mate

    # Shorten timeout for testing
    orig_timeout = v9_autonomous_agent.IDLE_TIMEOUT
    orig_interval = v9_autonomous_agent.IDLE_POLL_INTERVAL
    v9_autonomous_agent.IDLE_TIMEOUT = 1
    v9_autonomous_agent.IDLE_POLL_INTERVAL = 1

    sub_messages = [{"role": "user", "content": "initial"}]
    result = tm._idle_phase(mate, sub_messages)
    assert result == "timeout", \
        f"Idle phase with no work should timeout, got '{result}'"

    v9_autonomous_agent.IDLE_TIMEOUT = orig_timeout
    v9_autonomous_agent.IDLE_POLL_INTERVAL = orig_interval
    inbox.unlink(missing_ok=True)
    print("PASS: test_idle_phase_returns_timeout_on_empty")
    return True


def test_claim_task_sets_owner_and_status():
    """Create a task, call _claim_task, verify task.owner is set and status becomes in_progress."""
    from v9_autonomous_agent import TeammateManager, Teammate, TASK_MGR

    tm = TeammateManager()
    tm.create_team("claim-test")
    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="claimer-test", team_name="claim-test", inbox_path=inbox)
    tm._teams["claim-test"]["claimer-test"] = mate

    task = TASK_MGR.create("Task to be claimed")
    sub_messages = [{"role": "user", "content": "initial"}]

    result = tm._claim_task(mate, task, sub_messages)
    assert result is True, "_claim_task should return True"

    claimed = TASK_MGR.get(task.id)
    assert claimed.owner == "claimer-test", \
        f"Task owner should be 'claimer-test', got '{claimed.owner}'"
    assert claimed.status == "in_progress", \
        f"Task status should be 'in_progress', got '{claimed.status}'"

    # Verify the task was injected into sub_messages
    assert len(sub_messages) >= 2, \
        "Claiming should inject a message into sub_messages"
    assert "auto-claimed" in sub_messages[-1]["content"].lower() or \
           task.subject in sub_messages[-1]["content"], \
        "Injected message should reference the claimed task"

    inbox.unlink(missing_ok=True)
    print("PASS: test_claim_task_sets_owner_and_status")
    return True


def test_reinject_identity_preserves_existing_content():
    """Set up messages with existing system content, call _reinject_identity,
    verify existing content is preserved (not overwritten)."""
    from v9_autonomous_agent import TeammateManager, Teammate

    mate = Teammate(name="charlie", team_name="delta", agent_id="charlie@delta")
    original_text = "Work on task X. This is important."
    sub_messages = [{"role": "user", "content": original_text}]

    TeammateManager._reinject_identity(mate, sub_messages)

    result_content = sub_messages[0]["content"]
    # Original content must still be present
    assert original_text in result_content, \
        "Original content must be preserved after identity injection"
    # Identity must be injected
    assert "charlie" in result_content, \
        "Teammate name must be present after injection"
    assert "delta" in result_content, \
        "Team name must be present after injection"
    assert "charlie@delta" in result_content, \
        "Agent ID must be present after injection"
    # Content should be longer than original (appended, not replaced)
    assert len(result_content) > len(original_text), \
        "Content should be appended to, not replaced"

    print("PASS: test_reinject_identity_preserves_existing_content")
    return True


# =============================================================================
# LLM Integration Tests
# =============================================================================

V9_TOOLS = [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
            TASK_CREATE_TOOL, TASK_LIST_TOOL, TASK_UPDATE_TOOL,
            TASK_OUTPUT_TOOL, TASK_STOP_TOOL,
            TEAM_CREATE_TOOL, SEND_MESSAGE_TOOL, TEAM_DELETE_TOOL]


def test_llm_v9_creates_team():
    """LLM uses TeamCreate to set up a new team (same capability as v8)."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = run_agent(
        client,
        "Create a new team called 'autonomous-team'. Use the TeamCreate tool.",
        V9_TOOLS,
        system="You are a team lead. Use TeamCreate to set up teams.",
    )

    team_calls = [c for c in calls if c[0] == "TeamCreate"]
    assert len(team_calls) >= 1, \
        f"Model should use TeamCreate, got: {[c[0] for c in calls]}"

    print(f"Tool calls: {len(calls)}, TeamCreate: {len(team_calls)}")
    print("PASS: test_llm_v9_creates_team")
    return True


def test_llm_v9_task_workflow():
    """LLM creates a task and lists tasks."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = run_agent(
        client,
        "Do the following:\n"
        "1) Create a task with subject 'Build API endpoints' and description 'REST API'\n"
        "2) List all tasks to verify it was created\n"
        "Execute both steps.",
        V9_TOOLS,
        system="You are a team lead. Use TaskCreate and TaskList tools.",
        max_turns=5,
    )

    tool_names = [c[0] for c in calls]
    assert "TaskCreate" in tool_names, f"Should use TaskCreate, got: {tool_names}"
    assert "TaskList" in tool_names, f"Should use TaskList, got: {tool_names}"

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_llm_v9_task_workflow")
    return True


def test_llm_v9_full_autonomous_flow():
    """LLM creates team, creates tasks, and sends message -- full v9 flow."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = run_agent(
        client,
        "Do the following in order:\n"
        "1) Create a team called 'dev-team' using TeamCreate\n"
        "2) Create a task 'Setup database' using TaskCreate\n"
        "3) Send a message to 'alice' saying 'Please review' using SendMessage\n"
        "Execute all three steps.",
        V9_TOOLS,
        system="You are a team lead. Use TeamCreate, TaskCreate, and SendMessage tools.",
        max_turns=10,
    )

    tool_names = [c[0] for c in calls]
    assert "TeamCreate" in tool_names, f"Should use TeamCreate, got: {tool_names}"
    assert "TaskCreate" in tool_names, f"Should use TaskCreate, got: {tool_names}"
    assert "SendMessage" in tool_names, f"Should use SendMessage, got: {tool_names}"

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_llm_v9_full_autonomous_flow")
    return True


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    sys.exit(0 if run_tests([
        # v9 autonomous loop structure
        test_v9_teammate_loop_has_idle_phase,
        test_v9_teammate_loop_auto_claiming,
        test_v9_teammate_loop_identity_injection,
        test_v9_teammate_loop_shutdown_on_request,
        test_v9_teammate_loop_context_compression,
        # v9 inherits v8 capabilities
        test_v9_inherits_v8_messaging,
        test_v9_message_types_complete,
        test_v9_teammate_tools_exclude_team_mgmt,
        test_v9_all_tools_count,
        # v9 specific mechanisms
        test_v9_idle_loop_unclaimed_filter,
        test_v9_broadcast_excludes_sender,
        test_v9_task_manager_thread_safety,
        test_v9_dependency_chain,
        test_v9_vs_v8c_loop_difference,
        test_v9_system_prompt_mentions_autonomous,
        # v9 constant tests
        test_idle_poll_interval_default,
        # v9 new mechanism tests
        test_idle_cycle_message_wake,
        test_idle_cycle_task_wake,
        test_idle_cycle_timeout,
        test_auto_claim_filters_blocked,
        test_auto_claim_filters_owned,
        test_identity_reinjection,
        test_plan_approval_approve,
        test_plan_approval_reject,
        test_idle_reasons,
        test_plan_approval_end_to_end,
        test_idle_phase_returns_timeout_on_empty,
        test_claim_task_sets_owner_and_status,
        test_reinject_identity_preserves_existing_content,
        # LLM integration
        test_llm_v9_creates_team,
        test_llm_v9_task_workflow,
        test_llm_v9_full_autonomous_flow,
    ]) else 1)
