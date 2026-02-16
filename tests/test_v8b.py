"""
Tests for v8b_messaging.py - File-based inbox and message protocol.

v8b adds messaging to teams: SendMessage tool, JSONL inbox per teammate,
check_inbox drain semantics, broadcast, and 5 message types.

Unit tests verify SendMessage, inbox JSONL format, check_inbox drain,
broadcast excludes sender, MESSAGE_TYPES, message routing.

LLM integration tests verify the model can use SendMessage.
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
from tests.helpers import TEAM_CREATE_TOOL, SEND_MESSAGE_TOOL, TEAM_DELETE_TOOL

from pathlib import Path
from v8b_messaging import (
    TeammateManager, Teammate, TaskManager,
    MESSAGE_TYPES, TEAMMATE_TOOLS, ALL_TOOLS, TEAMS_DIR,
)


# =============================================================================
# Unit Tests - Messaging
# =============================================================================

def test_send_message():
    """Verify send_message writes to recipient inbox file."""
    tm = TeammateManager()
    tm.create_team("msg-team")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    teammate = Teammate(name="alice", team_name="msg-team", inbox_path=inbox)
    tm._teams["msg-team"]["alice"] = teammate

    tm.send_message("alice", "Hello Alice!", msg_type="message", team_name="msg-team")

    assert inbox.exists(), "Inbox file should exist after sending message"
    content = inbox.read_text()
    assert "Hello Alice!" in content

    inbox.unlink(missing_ok=True)
    print("PASS: test_send_message")
    return True


def test_check_inbox_drain():
    """Verify check_inbox returns all messages and empties the inbox."""
    tm = TeammateManager()
    tm.create_team("drain-team")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    teammate = Teammate(name="alice", team_name="drain-team", inbox_path=inbox)
    tm._teams["drain-team"]["alice"] = teammate

    tm.send_message("alice", "First", msg_type="message", team_name="drain-team")
    tm.send_message("alice", "Second", msg_type="message", team_name="drain-team")

    msgs = tm.check_inbox("alice", "drain-team")
    assert len(msgs) == 2, f"Expected 2, got {len(msgs)}"
    assert msgs[0]["content"] == "First"
    assert msgs[1]["content"] == "Second"

    # After draining, inbox should be empty
    msgs_after = tm.check_inbox("alice", "drain-team")
    assert len(msgs_after) == 0, f"Inbox should be empty after drain, got {len(msgs_after)}"

    inbox.unlink(missing_ok=True)
    print("PASS: test_check_inbox_drain")
    return True


def test_inbox_jsonl_format():
    """Verify inbox uses JSONL format (one JSON object per line)."""
    tm = TeammateManager()
    tm.create_team("jsonl-team")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    teammate = Teammate(name="fmt-test", team_name="jsonl-team", inbox_path=inbox)
    tm._teams["jsonl-team"]["fmt-test"] = teammate

    tm.send_message("fmt-test", "Msg 1", msg_type="message", team_name="jsonl-team")
    tm.send_message("fmt-test", "Msg 2", msg_type="broadcast", team_name="jsonl-team")

    with open(inbox) as f:
        lines = [l.strip() for l in f if l.strip()]

    assert len(lines) == 2, f"Expected 2 JSONL lines, got {len(lines)}"
    for i, line in enumerate(lines):
        data = json.loads(line)
        assert "type" in data, f"Line {i}: missing 'type'"
        assert "content" in data, f"Line {i}: missing 'content'"

    inbox.unlink(missing_ok=True)
    print("PASS: test_inbox_jsonl_format")
    return True


def test_message_types_constant():
    """Verify MESSAGE_TYPES includes all 5 required types."""
    expected = {"message", "broadcast", "shutdown_request",
                "shutdown_response", "plan_approval_response"}
    assert MESSAGE_TYPES == expected, \
        f"MESSAGE_TYPES should be {expected}, got {MESSAGE_TYPES}"
    print("PASS: test_message_types_constant")
    return True


def test_all_message_types_delivered():
    """Verify all 5 message types can be sent and received."""
    tm = TeammateManager()
    tm.create_team("alltype-team")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    teammate = Teammate(name="tester", team_name="alltype-team", inbox_path=inbox)
    tm._teams["alltype-team"]["tester"] = teammate

    all_types = sorted(MESSAGE_TYPES)
    for msg_type in all_types:
        tm.send_message("tester", f"Content for {msg_type}",
                        msg_type=msg_type, team_name="alltype-team")

    msgs = tm.check_inbox("tester", "alltype-team")
    assert len(msgs) == 5, f"Expected 5 messages, got {len(msgs)}"

    received_types = {m["type"] for m in msgs}
    assert received_types == MESSAGE_TYPES, \
        f"Received types mismatch: expected {MESSAGE_TYPES}, got {received_types}"

    inbox.unlink(missing_ok=True)
    print("PASS: test_all_message_types_delivered")
    return True


def test_broadcast_sends_to_all_except_sender():
    """Verify broadcast sends to all teammates except the sender."""
    tm = TeammateManager()
    tm.create_team("bcast-team")

    inboxes = {}
    for name in ["lead", "worker1", "worker2"]:
        inbox = Path(tempfile.mktemp(suffix=".jsonl"))
        mate = Teammate(name=name, team_name="bcast-team", inbox_path=inbox)
        tm._teams["bcast-team"][name] = mate
        inboxes[name] = inbox

    tm.send_message("", "Announcement", msg_type="broadcast",
                    sender="lead", team_name="bcast-team")

    lead_msgs = tm.check_inbox("lead", "bcast-team")
    assert len(lead_msgs) == 0, f"Sender should NOT receive broadcast, got {len(lead_msgs)}"

    for name in ["worker1", "worker2"]:
        msgs = tm.check_inbox(name, "bcast-team")
        assert len(msgs) >= 1, f"{name} should receive broadcast"
        assert "Announcement" in msgs[0]["content"]

    for inbox in inboxes.values():
        inbox.unlink(missing_ok=True)
    print("PASS: test_broadcast_sends_to_all_except_sender")
    return True


def test_broadcast_to_many_teammates():
    """Verify broadcast to 5+ teammates (excluding sender)."""
    tm = TeammateManager()
    tm.create_team("big-bcast")

    inboxes = []
    names = ["sender"] + [f"worker{i}" for i in range(5)]
    for name in names:
        inbox = Path(tempfile.mktemp(suffix=".jsonl"))
        mate = Teammate(name=name, team_name="big-bcast", inbox_path=inbox)
        tm._teams["big-bcast"][name] = mate
        inboxes.append(inbox)

    tm.send_message("", "Team update", msg_type="broadcast",
                    sender="sender", team_name="big-bcast")

    sender_msgs = tm.check_inbox("sender", "big-bcast")
    assert len(sender_msgs) == 0, "Sender should not receive broadcast"

    for i in range(5):
        msgs = tm.check_inbox(f"worker{i}", "big-bcast")
        assert len(msgs) == 1, f"worker{i} should get 1 broadcast, got {len(msgs)}"

    for inbox in inboxes:
        inbox.unlink(missing_ok=True)
    print("PASS: test_broadcast_to_many_teammates")
    return True


def test_broadcast_with_no_other_teammates():
    """Verify broadcast with only sender reaches 0 recipients."""
    tm = TeammateManager()
    tm.create_team("empty-bcast")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="lonely", team_name="empty-bcast", inbox_path=inbox)
    tm._teams["empty-bcast"]["lonely"] = mate

    result = tm.send_message("", "Nobody here", msg_type="broadcast",
                             sender="lonely", team_name="empty-bcast")
    assert "0" in result, f"Should reach 0 teammates, got: {result}"

    msgs = tm.check_inbox("lonely", "empty-bcast")
    assert len(msgs) == 0, "Sender should not receive own broadcast"

    inbox.unlink(missing_ok=True)
    print("PASS: test_broadcast_with_no_other_teammates")
    return True


def test_broadcast_no_recipient_required():
    """Verify broadcast works with empty recipient string."""
    tm = TeammateManager()
    tm.create_team("bcast-nr")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    mate = Teammate(name="recv", team_name="bcast-nr", inbox_path=inbox)
    tm._teams["bcast-nr"]["recv"] = mate

    result = tm.send_message("", "Hello all", msg_type="broadcast",
                             sender="lead", team_name="bcast-nr")
    assert "error" not in result.lower(), f"Should succeed, got: {result}"
    msgs = tm.check_inbox("recv", "bcast-nr")
    assert len(msgs) >= 1

    inbox.unlink(missing_ok=True)
    print("PASS: test_broadcast_no_recipient_required")
    return True


def test_message_requires_recipient():
    """Verify message to nonexistent recipient returns error."""
    tm = TeammateManager()
    tm.create_team("recip-test")
    result = tm.send_message("nonexistent", "Hello", msg_type="message",
                             team_name="recip-test")
    assert "error" in result.lower() or "not found" in result.lower(), \
        f"Message to nonexistent recipient should fail, got: {result}"
    print("PASS: test_message_requires_recipient")
    return True


def test_v8b_has_send_message_tool():
    """Verify v8b ALL_TOOLS includes SendMessage."""
    all_names = {t["name"] for t in ALL_TOOLS}
    assert "SendMessage" in all_names, "v8b ALL_TOOLS must include SendMessage"
    print("PASS: test_v8b_has_send_message_tool")
    return True


def test_v8b_teammate_tools_have_send_message():
    """Verify TEAMMATE_TOOLS includes SendMessage."""
    tool_names = {t["name"] for t in TEAMMATE_TOOLS}
    assert "SendMessage" in tool_names, "TEAMMATE_TOOLS must include SendMessage"
    print("PASS: test_v8b_teammate_tools_have_send_message")
    return True


def test_v8b_tool_count():
    """Verify v8b has 15 tools (v8a's 14 + SendMessage)."""
    assert len(ALL_TOOLS) == 15, f"v8b should have 15 tools, got {len(ALL_TOOLS)}"
    print("PASS: test_v8b_tool_count")
    return True


def test_v8b_teammate_tools_subset():
    """Verify TEAMMATE_TOOLS is a strict subset of ALL_TOOLS."""
    teammate_names = {t["name"] for t in TEAMMATE_TOOLS}
    all_names = {t["name"] for t in ALL_TOOLS}
    assert teammate_names.issubset(all_names), \
        f"Extra: {teammate_names - all_names}"
    assert len(TEAMMATE_TOOLS) < len(ALL_TOOLS), \
        "TEAMMATE_TOOLS should have fewer tools than ALL_TOOLS"
    print("PASS: test_v8b_teammate_tools_subset")
    return True


def test_check_inbox_atomicity():
    """Verify check_inbox uses lock file to prevent race."""
    tm = TeammateManager()
    tm.create_team("lock-team")

    inbox = Path(tempfile.mktemp(suffix=".jsonl"))
    teammate = Teammate(name="locker", team_name="lock-team", inbox_path=inbox)
    tm._teams["lock-team"]["locker"] = teammate

    tm.send_message("locker", "msg1", msg_type="message", team_name="lock-team")

    lock_path = inbox.with_suffix(".lock")
    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        msgs = tm.check_inbox("locker", "lock-team")
        assert msgs == [], "check_inbox should return empty when lock is held"
    finally:
        os.close(fd)
        lock_path.unlink(missing_ok=True)

    msgs = tm.check_inbox("locker", "lock-team")
    assert len(msgs) == 1, f"Should get message after lock released, got {len(msgs)}"

    inbox.unlink(missing_ok=True)
    print("PASS: test_check_inbox_atomicity")
    return True


def test_shutdown_via_delete():
    """Verify delete_team sends shutdown_request to all teammates."""
    tm = TeammateManager()
    tm.create_team("shutdown-team")

    inbox_a = Path(tempfile.mktemp(suffix=".jsonl"))
    inbox_b = Path(tempfile.mktemp(suffix=".jsonl"))
    mate_a = Teammate(name="alpha", team_name="shutdown-team", inbox_path=inbox_a)
    mate_b = Teammate(name="beta", team_name="shutdown-team", inbox_path=inbox_b)
    tm._teams["shutdown-team"]["alpha"] = mate_a
    tm._teams["shutdown-team"]["beta"] = mate_b

    result = tm.delete_team("shutdown-team")
    assert "deleted" in result.lower()

    assert mate_a.status == "shutdown"
    assert mate_b.status == "shutdown"

    for inbox, name in [(inbox_a, "alpha"), (inbox_b, "beta")]:
        assert inbox.exists(), f"Inbox for {name} should exist"
        msgs = []
        with open(inbox, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    msgs.append(json.loads(line))
        shutdown_msgs = [m for m in msgs if m.get("type") == "shutdown_request"]
        assert len(shutdown_msgs) >= 1, \
            f"Expected shutdown_request in {name}'s inbox, got {len(shutdown_msgs)}"

    inbox_a.unlink(missing_ok=True)
    inbox_b.unlink(missing_ok=True)
    print("PASS: test_shutdown_via_delete")
    return True


# =============================================================================
# LLM Integration Tests
# =============================================================================

V8B_TOOLS = [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL,
             TASK_CREATE_TOOL, TASK_LIST_TOOL, TASK_UPDATE_TOOL,
             TASK_OUTPUT_TOOL, TASK_STOP_TOOL,
             TEAM_CREATE_TOOL, SEND_MESSAGE_TOOL, TEAM_DELETE_TOOL]


def test_llm_sends_message():
    """LLM uses SendMessage to communicate with a teammate."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = run_agent(
        client,
        "You MUST call the SendMessage tool right now with these parameters: "
        "type='message', recipient='alice', content='Please review the API code'. "
        "Do NOT respond with text. Just call the SendMessage tool.",
        V8B_TOOLS,
        system="You are a team lead. You MUST use the SendMessage tool when asked.",
    )

    msg_calls = [c for c in calls if c[0] == "SendMessage"]
    assert len(msg_calls) >= 1, \
        f"Model should use SendMessage, got: {[c[0] for c in calls]}"

    print(f"Tool calls: {len(calls)}, SendMessage: {len(msg_calls)}")
    print("PASS: test_llm_sends_message")
    return True


def test_llm_broadcasts():
    """LLM uses SendMessage with type='broadcast'."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = run_agent(
        client,
        "Broadcast a message to all teammates: 'Stop all work, critical bug found'. "
        "Use SendMessage with type='broadcast'.",
        V8B_TOOLS,
        system="You are a team lead. Use SendMessage with type='broadcast'.",
    )

    msg_calls = [c for c in calls if c[0] == "SendMessage"]
    assert len(msg_calls) >= 1
    assert msg_calls[0][1].get("type") == "broadcast", \
        f"Should use broadcast type, got: {msg_calls[0][1].get('type')}"

    print(f"Tool calls: {len(calls)}, SendMessage: {len(msg_calls)}")
    print("PASS: test_llm_broadcasts")
    return True


def test_llm_team_workflow():
    """LLM creates team, sends message, deletes team -- full lifecycle."""
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    text, calls, _ = run_agent(
        client,
        "Do the following in order:\n"
        "1) Create a team called 'build-team' using TeamCreate\n"
        "2) Send a message to 'bob' saying 'Start the build' using SendMessage\n"
        "3) Delete the team using TeamDelete\n"
        "Execute all three steps.",
        V8B_TOOLS,
        system="You are a team lead. Use TeamCreate, SendMessage, and TeamDelete.",
        max_turns=10,
    )

    tool_names = [c[0] for c in calls]
    assert "TeamCreate" in tool_names
    assert "SendMessage" in tool_names
    assert "TeamDelete" in tool_names

    print(f"Tool calls: {len(calls)}")
    print("PASS: test_llm_team_workflow")
    return True


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    sys.exit(0 if run_tests([
        test_send_message,
        test_check_inbox_drain,
        test_inbox_jsonl_format,
        test_message_types_constant,
        test_all_message_types_delivered,
        test_broadcast_sends_to_all_except_sender,
        test_broadcast_to_many_teammates,
        test_broadcast_with_no_other_teammates,
        test_broadcast_no_recipient_required,
        test_message_requires_recipient,
        test_v8b_has_send_message_tool,
        test_v8b_teammate_tools_have_send_message,
        test_v8b_tool_count,
        test_v8b_teammate_tools_subset,
        test_check_inbox_atomicity,
        test_shutdown_via_delete,
        # LLM integration
        test_llm_sends_message,
        test_llm_broadcasts,
        test_llm_team_workflow,
    ]) else 1)
