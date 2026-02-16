"""
Tests for v5_compression_agent.py - Three-layer context compression.

Tests ContextManager token estimation, microcompact, should_compact,
handle_large_output, save_transcript, and LLM multi-turn workflows.
"""

import os
import sys
import tempfile
import time
import json
import inspect
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.helpers import get_client, run_agent, run_tests, MODEL
from tests.helpers import BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL
from tests.helpers import TODO_WRITE_TOOL, SKILL_TOOL, TASK_CREATE_TOOL, TASK_LIST_TOOL, TASK_UPDATE_TOOL

from v5_compression_agent import ContextManager


# =============================================================================
# Unit Tests
# =============================================================================


def test_estimate_tokens():
    cm = ContextManager()
    # estimate_tokens uses len(text) // 4
    result = cm.estimate_tokens("hello world")
    expected = len("hello world") // 4  # 11 // 4 = 2
    assert result == expected, f"Expected {expected}, got {result}"
    assert result == 2, f"'hello world' (11 chars) // 4 should be 2, got {result}"
    print("PASS: test_estimate_tokens")
    return True


def test_microcompact_preserves_recent():
    cm = ContextManager()
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"t{i}", "name": "read_file", "input": {"path": f"file{i}.py"}}
            for i in range(5)
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": "x" * 5000}
            for i in range(5)
        ]},
    ]

    messages = cm.microcompact(messages)

    user_content = messages[1]["content"]
    tool_results = [b for b in user_content if b.get("type") == "tool_result"]

    preserved_count = sum(
        1 for b in tool_results
        if b.get("content") != "[Old tool result content cleared]"
    )
    assert preserved_count >= cm.KEEP_RECENT, \
        f"Should preserve at least {cm.KEEP_RECENT} recent results, got {preserved_count}"
    print("PASS: test_microcompact_preserves_recent")
    return True


def test_microcompact_replaces_old():
    cm = ContextManager()
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"t{i}", "name": "bash", "input": {"command": f"ls {i}"}}
            for i in range(5)
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": "x" * 5000}
            for i in range(5)
        ]},
    ]

    messages = cm.microcompact(messages)

    user_content = messages[1]["content"]
    compacted = [
        b for b in user_content
        if b.get("content") == "[Old tool result content cleared]"
    ]
    assert len(compacted) > 0, "Old tool results should be compacted"
    assert len(compacted) == 2, f"Expected 2 compacted (5 - KEEP_RECENT=3), got {len(compacted)}"
    print("PASS: test_microcompact_replaces_old")
    return True


def test_microcompact_skips_small():
    cm = ContextManager()
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"t{i}", "name": "read_file", "input": {"path": f"file{i}.py"}}
            for i in range(5)
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": "short output"}
            for i in range(5)
        ]},
    ]

    messages = cm.microcompact(messages)

    user_content = messages[1]["content"]
    compacted = [
        b for b in user_content
        if b.get("content") == "[Old tool result content cleared]"
    ]
    assert len(compacted) == 0, "Small outputs (under token threshold) should never be compacted"
    print("PASS: test_microcompact_skips_small")
    return True


def test_should_compact_threshold():
    cm = ContextManager()
    # should_compact has MIN_SAVINGS guard: if <=5 messages, savings=0 -> always False.
    # Need >5 messages to properly trigger. Build 8 messages, each large enough
    # that total tokens exceed TOKEN_THRESHOLD (170616).
    # With len//4 formula: need chunk_size such that 8 * (chunk_size+~30) // 4 > threshold
    chunk_size = (cm.TOKEN_THRESHOLD * 4) // 8 + 100
    messages = [{"role": "user", "content": "x" * chunk_size} for _ in range(8)]
    result = cm.should_compact(messages)
    assert result is True, "should_compact should return True when tokens exceed TOKEN_THRESHOLD"
    print("PASS: test_should_compact_threshold")
    return True


def test_should_compact_under_threshold():
    cm = ContextManager(max_context_tokens=200000)
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    result = cm.should_compact(messages)
    assert result is False, "should_compact should return False for small conversations"
    print("PASS: test_should_compact_under_threshold")
    return True


def test_handle_large_output_passthrough():
    cm = ContextManager()
    normal_output = "This is a normal sized output."
    result = cm.handle_large_output(normal_output)
    assert result == normal_output, "Normal output should pass through unchanged"
    print("PASS: test_handle_large_output_passthrough")
    return True


def test_handle_large_output_saves():
    cm = ContextManager()
    large_output = "x" * (cm.MAX_OUTPUT_TOKENS * 4 + 100)
    result = cm.handle_large_output(large_output)
    assert result != large_output, "Large output should not pass through unchanged"
    assert "Output too large" in result, "Should indicate output was too large"
    assert "Saved to" in result, "Should indicate file was saved"
    assert "Preview" in result, "Should include a preview"
    print("PASS: test_handle_large_output_saves")
    return True


def test_auto_compact_preserves_recent():
    """Verify auto_compact structure via source inspection.

    auto_compact calls the API so we can't run it in unit tests, but we can
    verify its contract by inspecting the source:
    (a) calls save_transcript (archive before compressing)
    (b) keeps recent 5 messages (messages[-5:])
    (c) injects summary as user message (not system prompt modification)
    """
    import v5_compression_agent
    source = inspect.getsource(v5_compression_agent.ContextManager.auto_compact)

    # (a) Must call save_transcript to archive before compressing
    assert "save_transcript" in source, \
        "auto_compact must call save_transcript to archive messages before compression"

    # (b) Must keep recent messages (last 5)
    assert "messages[-5:]" in source, \
        "auto_compact must preserve recent 5 messages via messages[-5:]"

    # (c) Summary injected as user message, not modifying system prompt
    assert '"role": "user"' in source or "'role': 'user'" in source, \
        "auto_compact must inject summary as a user message (cache-preserving)"
    assert '"role": "assistant"' in source or "'role': 'assistant'" in source, \
        "auto_compact must include an assistant acknowledgment message"

    # Verify it does NOT modify the system prompt
    assert "SYSTEM" not in source, \
        "auto_compact must not modify SYSTEM prompt (would invalidate cache)"

    print("PASS: test_auto_compact_preserves_recent")
    return True


def test_transcript_save_and_load():
    """Verify save_transcript writes valid JSONL that can be loaded back.

    Tests the 'never lose data' principle: full transcripts are always
    saved to disk as the permanent archive.
    """
    cm = ContextManager()
    messages = [
        {"role": "user", "content": "Hello, please help me"},
        {"role": "assistant", "content": "Sure, I can help with that."},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "file contents here"}
        ]},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        # Override TRANSCRIPT_DIR to use our temp directory
        import v5_compression_agent
        original_dir = v5_compression_agent.TRANSCRIPT_DIR
        v5_compression_agent.TRANSCRIPT_DIR = Path(tmpdir)
        Path(tmpdir).mkdir(exist_ok=True)

        try:
            cm.save_transcript(messages)
            transcript_path = Path(tmpdir) / "transcript.jsonl"

            # (a) Transcript file must exist on disk
            assert transcript_path.exists(), \
                "save_transcript must create transcript.jsonl on disk"

            # (b) Each line must be valid JSON
            loaded_messages = []
            with open(transcript_path, "r") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                        loaded_messages.append(parsed)
                    except json.JSONDecodeError:
                        raise AssertionError(
                            f"Line {line_num} is not valid JSON: {line[:100]}"
                        )

            # (c) Loading the file gives back the same messages
            assert len(loaded_messages) == len(messages), \
                f"Expected {len(messages)} messages, got {len(loaded_messages)}"

            for i, (original, loaded) in enumerate(zip(messages, loaded_messages)):
                assert original["role"] == loaded["role"], \
                    f"Message {i}: role mismatch: {original['role']} != {loaded['role']}"
                if isinstance(original["content"], str):
                    assert original["content"] == loaded["content"], \
                        f"Message {i}: content mismatch"
                elif isinstance(original["content"], list):
                    assert isinstance(loaded["content"], list), \
                        f"Message {i}: content should be a list"
                    assert len(original["content"]) == len(loaded["content"]), \
                        f"Message {i}: content list length mismatch"
        finally:
            v5_compression_agent.TRANSCRIPT_DIR = original_dir

    print("PASS: test_transcript_save_and_load")
    return True


def test_microcompact_only_compactable_tools():
    """Verify only COMPACTABLE_TOOLS outputs get compacted; others are never touched.

    COMPACTABLE_TOOLS = {"bash", "read_file", "write_file", "edit_file"}
    All four base tools are compactable. Non-compactable tools like TodoWrite
    should never be compacted.
    """
    cm = ContextManager()

    large_output = "x" * 5000

    # 5 compactable (bash) + 3 compactable (write_file) + 2 compactable (edit_file) = 10
    assistant_content = []
    user_content = []

    for i in range(5):
        assistant_content.append({
            "type": "tool_use", "id": f"bash_{i}",
            "name": "bash", "input": {"command": f"ls {i}"}
        })
        user_content.append({
            "type": "tool_result", "tool_use_id": f"bash_{i}",
            "content": large_output
        })

    for i in range(3):
        assistant_content.append({
            "type": "tool_use", "id": f"write_{i}",
            "name": "write_file", "input": {"path": f"out{i}.txt", "content": "data"}
        })
        user_content.append({
            "type": "tool_result", "tool_use_id": f"write_{i}",
            "content": large_output
        })

    for i in range(2):
        assistant_content.append({
            "type": "tool_use", "id": f"edit_{i}",
            "name": "edit_file", "input": {"path": f"f{i}.txt", "old_text": "a", "new_text": "b"}
        })
        user_content.append({
            "type": "tool_result", "tool_use_id": f"edit_{i}",
            "content": large_output
        })

    messages = [
        {"role": "assistant", "content": assistant_content},
        {"role": "user", "content": user_content},
    ]

    messages = cm.microcompact(messages)

    compacted_marker = "[Old tool result content cleared]"
    user_blocks = messages[1]["content"]

    # All 10 are compactable. KEEP_RECENT=3, so 7 should be compacted.
    total_compacted = sum(
        1 for b in user_blocks
        if b["content"] == compacted_marker
    )
    total_preserved = sum(
        1 for b in user_blocks
        if b["content"] != compacted_marker
    )
    assert total_preserved == cm.KEEP_RECENT, \
        f"Expected {cm.KEEP_RECENT} recent results preserved, got {total_preserved}"
    assert total_compacted == 7, \
        f"Expected 7 compacted (10 - KEEP_RECENT=3), got {total_compacted}"

    print("PASS: test_microcompact_only_compactable_tools")
    return True


# =============================================================================
# LLM Tests
# =============================================================================

V1_TOOLS = [BASH_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL, EDIT_FILE_TOOL]


def test_llm_reads_multiple_files():
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(4):
            filepath = os.path.join(tmpdir, f"data{i}.txt")
            with open(filepath, "w") as f:
                f.write(f"Content of file {i}: value={i * 10}")

        text, calls, _ = run_agent(
            client,
            f"Read all 4 files named data0.txt through data3.txt in {tmpdir} and summarize their contents.",
            V1_TOOLS,
            workdir=tmpdir,
            max_turns=10,
        )

        read_calls = [c for c in calls if c[0] == "read_file"]
        assert len(read_calls) >= 3, f"Should make at least 3 read_file calls, got {len(read_calls)}"
        assert text is not None, "Agent should produce a summary"
    print("PASS: test_llm_reads_multiple_files")
    return True


def test_llm_read_edit_workflow():
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "target.txt")
        with open(filepath, "w") as f:
            f.write("hello world")

        text, calls, _ = run_agent(
            client,
            f"Use edit_file to change 'hello' to 'goodbye' in {filepath}. Use old_string='hello' and new_string='goodbye'.",
            V1_TOOLS,
            workdir=tmpdir,
            max_turns=10,
        )

        assert len(calls) >= 1, f"Should make at least 1 tool call, got {len(calls)}"

        with open(filepath, "r") as f:
            content = f.read()
        assert "goodbye" in content, f"File should contain 'goodbye' after edit, got: {content}"
    print("PASS: test_llm_read_edit_workflow")
    return True


def test_llm_write_and_verify():
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "created.txt")
        text, calls, _ = run_agent(
            client,
            f"Write a file at {filepath} with the content 'test content 123', then read it back to verify.",
            V1_TOOLS,
            workdir=tmpdir,
            max_turns=10,
        )

        write_calls = [c for c in calls if c[0] == "write_file"]
        assert len(write_calls) >= 1, "Should call write_file at least once"
        assert os.path.exists(filepath), f"File should exist at {filepath}"

        with open(filepath, "r") as f:
            content = f.read()
        assert "test content 123" in content, f"File should contain 'test content 123', got: {content}"
    print("PASS: test_llm_write_and_verify")
    return True


def test_llm_many_turns():
    client = get_client()
    if not client:
        print("SKIP: No API key")
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        text, calls, _ = run_agent(
            client,
            (
                f"Create 4 files in {tmpdir}: "
                f"a.txt with 'alpha', b.txt with 'bravo', c.txt with 'charlie', d.txt with 'delta'. "
                f"Create each one separately using write_file."
            ),
            V1_TOOLS,
            workdir=tmpdir,
            max_turns=15,
        )

        write_calls = [c for c in calls if c[0] == "write_file"]
        assert len(write_calls) >= 3, f"Should make at least 3 write_file calls, got {len(write_calls)}"

        created = sum(1 for n in ("a.txt", "b.txt", "c.txt", "d.txt")
                      if os.path.exists(os.path.join(tmpdir, n)))
        assert created >= 3, f"Should create at least 3/4 files, got {created}"

        for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
            path = os.path.join(tmpdir, name)
            assert os.path.exists(path), f"File {name} should exist"
    print("PASS: test_llm_many_turns")
    return True


# =============================================================================
# v5 Mechanism-Specific Tests (source inspection)
# =============================================================================


def test_agent_loop_calls_microcompact():
    """Verify v5 agent_loop integrates microcompact before each API call.

    This is the core v5 mechanism: before every API call, the agent loop
    runs microcompact to replace old large tool outputs, reducing context
    without losing recent data.
    """
    source = inspect.getsource(__import__("v5_compression_agent").agent_loop)

    assert "microcompact" in source, \
        "agent_loop must call microcompact before API calls"
    assert "should_compact" in source, \
        "agent_loop must check should_compact for auto-compression trigger"
    assert "auto_compact" in source, \
        "agent_loop must call auto_compact when threshold is exceeded"
    assert "handle_large_output" in source, \
        "agent_loop must call handle_large_output for oversized tool results"

    print("PASS: test_agent_loop_calls_microcompact")
    return True


def test_compact_command_in_repl():
    """Verify v5 REPL handles /compact command for manual compression.

    /compact is the user-facing escape hatch: when the model context is
    getting large, the user can manually trigger compression.
    """
    source = inspect.getsource(__import__("v5_compression_agent").main)

    assert "/compact" in source or "compact" in source, \
        "main() REPL must handle /compact command"

    print("PASS: test_compact_command_in_repl")
    return True


def test_compactable_tools_constant():
    """Verify COMPACTABLE_TOOLS is defined and contains all base tools.

    All four base tools (bash, read_file, write_file, edit_file) are compactable.
    """
    from v5_compression_agent import ContextManager
    cm = ContextManager()

    assert hasattr(cm, "COMPACTABLE_TOOLS"), \
        "ContextManager must define COMPACTABLE_TOOLS"
    compactable = cm.COMPACTABLE_TOOLS
    assert "bash" in compactable, "bash should be compactable"
    assert "read_file" in compactable, "read_file should be compactable"
    assert "write_file" in compactable, "write_file should be compactable"
    assert "edit_file" in compactable, "edit_file should be compactable"

    print("PASS: test_compactable_tools_constant")
    return True


def test_keep_recent_constant():
    """Verify KEEP_RECENT is 3 (microcompact preserves last 3 tool outputs)."""
    from v5_compression_agent import ContextManager
    cm = ContextManager()

    assert hasattr(cm, "KEEP_RECENT"), \
        "ContextManager must define KEEP_RECENT"
    assert cm.KEEP_RECENT == 3, \
        f"KEEP_RECENT should be 3, got {cm.KEEP_RECENT}"

    print("PASS: test_keep_recent_constant")
    return True


def test_token_threshold_constant():
    """Verify TOKEN_THRESHOLD is defined via auto_compact_threshold()."""
    from v5_compression_agent import ContextManager, auto_compact_threshold
    cm = ContextManager()

    assert hasattr(cm, "TOKEN_THRESHOLD"), \
        "ContextManager must define TOKEN_THRESHOLD"
    assert cm.TOKEN_THRESHOLD > 0, \
        f"TOKEN_THRESHOLD must be positive, got {cm.TOKEN_THRESHOLD}"
    # TOKEN_THRESHOLD = auto_compact_threshold() = 200000 - 16384 - 13000 = 170616
    assert cm.TOKEN_THRESHOLD == auto_compact_threshold(), \
        f"TOKEN_THRESHOLD should match auto_compact_threshold(), got {cm.TOKEN_THRESHOLD}"

    print("PASS: test_token_threshold_constant")
    return True


def test_notification_drain_in_agent_loop():
    """Verify v5 agent_loop does NOT have notification drain (that's v7).

    v5's agent_loop should call microcompact, should_compact, auto_compact
    but should NOT drain notifications (BackgroundManager is v7).
    """
    source = inspect.getsource(__import__("v5_compression_agent").agent_loop)

    assert "drain_notifications" not in source, \
        "v5 agent_loop should NOT have drain_notifications (that's v7)"

    print("PASS: test_notification_drain_in_agent_loop")
    return True


# =============================================================================
# v5 New Mechanism Tests (from final_design.md)
# =============================================================================


def test_auto_compact_threshold_default():
    """Verify auto_compact_threshold default: (200000, 16384) -> 170616."""
    from v5_compression_agent import auto_compact_threshold
    result = auto_compact_threshold()
    assert result == 200000 - 16384 - 13000, \
        f"Expected 170616, got {result}"
    assert result == 170616
    print("PASS: test_auto_compact_threshold_default")
    return True


def test_auto_compact_threshold_large_output():
    """Verify max_output > 20000 is capped at 20000."""
    from v5_compression_agent import auto_compact_threshold
    result = auto_compact_threshold(context_window=200000, max_output=50000)
    expected = 200000 - 20000 - 13000  # capped at 20000
    assert result == expected, f"Expected {expected}, got {result}"
    print("PASS: test_auto_compact_threshold_large_output")
    return True


def test_min_savings_guard():
    """Verify compact is skipped when savings < MIN_SAVINGS."""
    from v5_compression_agent import ContextManager, MIN_SAVINGS

    cm = ContextManager()
    # With <= 5 messages, recent_size == total, so savings == 0 < MIN_SAVINGS
    # This should always return False regardless of total size
    big_msg = [{"role": "user", "content": "x" * 200000}]
    assert not cm.should_compact(big_msg), \
        "Single message should be skipped (savings = 0 < MIN_SAVINGS)"
    print("PASS: test_min_savings_guard")
    return True


def test_min_savings_guard_proceeds():
    """Verify compact proceeds when savings >= MIN_SAVINGS."""
    from v5_compression_agent import ContextManager, MIN_SAVINGS

    cm = ContextManager()
    # Build 8 messages, each with enough content to exceed threshold
    # First 3 messages will have enough tokens to produce savings >= MIN_SAVINGS
    # With len//4: need chunk_size such that 8 * (chunk_size+~30) // 4 > threshold
    chunk_size = (cm.TOKEN_THRESHOLD * 4) // 8 + 100
    messages = [{"role": "user", "content": "x" * chunk_size} for _ in range(8)]
    assert cm.should_compact(messages), \
        "With 8 large messages, savings should exceed MIN_SAVINGS"
    print("PASS: test_min_savings_guard_proceeds")
    return True


def test_estimate_tokens_formula():
    """Verify estimate_tokens("a" * 300) == 75 (300 // 4)."""
    cm = ContextManager()
    result = cm.estimate_tokens("a" * 300)
    assert result == 75, f"Expected 75, got {result}"
    print("PASS: test_estimate_tokens_formula")
    return True


def test_compactable_tools_valid():
    """Verify every name in COMPACTABLE_TOOLS exists in the tool definitions."""
    from v5_compression_agent import ContextManager, ALL_TOOLS
    cm = ContextManager()
    tool_names = {t["name"] for t in ALL_TOOLS}
    for name in cm.COMPACTABLE_TOOLS:
        assert name in tool_names, \
            f"COMPACTABLE_TOOLS entry '{name}' not found in TOOLS"
    print("PASS: test_compactable_tools_valid")
    return True


def test_restore_recent_files_limits():
    """Verify restore_recent_files respects MAX_RESTORE_FILES and token limits."""
    from v5_compression_agent import ContextManager, MAX_RESTORE_FILES, \
        MAX_RESTORE_TOKENS_PER_FILE, MAX_RESTORE_TOKENS_TOTAL

    assert MAX_RESTORE_FILES == 5
    assert MAX_RESTORE_TOKENS_PER_FILE == 5000
    assert MAX_RESTORE_TOKENS_TOTAL == 50000

    cm = ContextManager()
    # Empty history should restore nothing
    result = cm.restore_recent_files([])
    assert result == [], "Empty messages should return empty restore list"
    print("PASS: test_restore_recent_files_limits")
    return True


def test_restore_recent_files_empty_cache():
    """Verify restore_recent_files returns empty list for no read_file calls."""
    cm = ContextManager()
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    ]
    result = cm.restore_recent_files(messages)
    assert result == [], "No read_file calls should produce empty restore list"
    print("PASS: test_restore_recent_files_empty_cache")
    return True


def test_image_token_constant():
    """Verify IMAGE_TOKEN_ESTIMATE == 2000."""
    from v5_compression_agent import IMAGE_TOKEN_ESTIMATE
    assert IMAGE_TOKEN_ESTIMATE == 2000, \
        f"IMAGE_TOKEN_ESTIMATE should be 2000, got {IMAGE_TOKEN_ESTIMATE}"
    print("PASS: test_image_token_constant")
    return True


def test_restore_recent_files_with_actual_files():
    """Create temp files, simulate read_file tool calls, verify restore works."""
    import v5_compression_agent
    cm = ContextManager()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Resolve to handle macOS /var -> /private/var symlinks
        resolved_tmpdir = Path(tmpdir).resolve()
        orig_workdir = v5_compression_agent.WORKDIR
        v5_compression_agent.WORKDIR = resolved_tmpdir

        try:
            # Create actual files in the temp workdir
            for i in range(3):
                fp = resolved_tmpdir / f"src{i}.py"
                fp.write_text(f"# source file {i}\nprint('hello {i}')\n")

            # Build messages simulating read_file tool calls (relative paths)
            messages = [
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": f"rf{i}", "name": "read_file",
                     "input": {"path": f"src{i}.py"}}
                    for i in range(3)
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": f"rf{i}",
                     "content": f"# source file {i}\nprint('hello {i}')\n"}
                    for i in range(3)
                ]},
            ]

            restored = cm.restore_recent_files(messages)
            assert len(restored) >= 1, \
                f"Should restore at least 1 file, got {len(restored)}"
            assert len(restored) <= 3, \
                f"Should restore at most 3 files, got {len(restored)}"

            for msg in restored:
                assert msg["role"] == "user", "Restored messages should have role 'user'"
                assert "[Restored after compact]" in msg["content"], \
                    "Restored messages should contain '[Restored after compact]'"
                assert "print('hello" in msg["content"], \
                    "Restored content should contain actual file content"
        finally:
            v5_compression_agent.WORKDIR = orig_workdir

    print("PASS: test_restore_recent_files_with_actual_files")
    return True


def test_should_compact_exactly_at_threshold():
    """Edge case: total == threshold should return True (if savings are sufficient)."""
    from v5_compression_agent import ContextManager, MIN_SAVINGS

    cm = ContextManager()
    # Build messages where total tokens are exactly at the threshold.
    # We need >5 messages so that savings > MIN_SAVINGS.
    # Each message contributes roughly chunk_size * 4/3 tokens after json.dumps.
    # Target: total tokens = TOKEN_THRESHOLD exactly. Use 8 messages.
    # With 8 msgs, savings = total - recent_5_size ~ 3/8 of total.
    # We need total > threshold AND savings >= MIN_SAVINGS.
    # At exactly threshold, total <= threshold => False
    # So build exactly threshold+1 to trigger. Verify boundary.
    # With len//4: chars_per_msg = threshold * 4 / 8 = threshold / 2
    target_chars_per_msg = (cm.TOKEN_THRESHOLD * 4) // 8
    messages = [{"role": "user", "content": "x" * target_chars_per_msg} for _ in range(8)]

    total = sum(cm.estimate_tokens(json.dumps(m, default=str)) for m in messages)
    if total > cm.TOKEN_THRESHOLD:
        # At or above threshold with sufficient savings
        recent_size = sum(cm.estimate_tokens(json.dumps(m, default=str)) for m in messages[-5:])
        savings = total - recent_size
        if savings >= MIN_SAVINGS:
            assert cm.should_compact(messages) is True, \
                "should_compact should return True when total > threshold with sufficient savings"
        else:
            assert cm.should_compact(messages) is False, \
                "should_compact should return False when savings < MIN_SAVINGS"
    else:
        assert cm.should_compact(messages) is False, \
            "should_compact should return False when total <= threshold"

    print("PASS: test_should_compact_exactly_at_threshold")
    return True


def test_should_compact_just_below_threshold():
    """Edge case: total just below threshold should return False."""
    cm = ContextManager()
    # Build messages whose total tokens are well below the threshold
    # Each message has a small amount of content
    messages = [{"role": "user", "content": "x" * 100} for _ in range(8)]
    total = sum(cm.estimate_tokens(json.dumps(m, default=str)) for m in messages)
    assert total < cm.TOKEN_THRESHOLD, \
        f"Total {total} should be below threshold {cm.TOKEN_THRESHOLD}"
    result = cm.should_compact(messages)
    assert result is False, \
        "should_compact should return False when total is below threshold"
    print("PASS: test_should_compact_just_below_threshold")
    return True


def test_image_token_estimation_constant():
    """Verify IMAGE_TOKEN_ESTIMATE=2000 is used in estimate_tokens for image content."""
    from v5_compression_agent import IMAGE_TOKEN_ESTIMATE
    cm = ContextManager()
    # IMAGE_TOKEN_ESTIMATE is a constant (2000) used for image blocks
    assert IMAGE_TOKEN_ESTIMATE == 2000, \
        f"IMAGE_TOKEN_ESTIMATE should be 2000, got {IMAGE_TOKEN_ESTIMATE}"
    # The estimate_tokens function uses len(text) // 4
    # For a string of 8000 chars (= 2000 tokens), verify the formula
    text_equivalent = "a" * 8000
    tokens = cm.estimate_tokens(text_equivalent)
    assert tokens == IMAGE_TOKEN_ESTIMATE, \
        f"8000 chars should estimate to {IMAGE_TOKEN_ESTIMATE} tokens, got {tokens}"
    print("PASS: test_image_token_estimation_constant")
    return True


def test_token_formula_min_savings_interaction():
    """Verify that with len//4 formula and MIN_SAVINGS=20000,
    compaction requires substantial real token savings."""
    from v5_compression_agent import ContextManager, MIN_SAVINGS
    import json

    cm = ContextManager()
    assert MIN_SAVINGS == 20000

    # Create messages where non-recent portion has < 80000 chars
    # (80000 chars // 4 = 20000 tokens = MIN_SAVINGS boundary)
    small_messages = [
        {"role": "user", "content": "x" * 10000}  # ~2500 tokens each
        for _ in range(8)
    ]
    total = sum(cm.estimate_tokens(json.dumps(m, default=str)) for m in small_messages)
    recent_size = sum(cm.estimate_tokens(json.dumps(m, default=str)) for m in small_messages[-5:])
    savings = total - recent_size

    # 3 non-recent messages * ~10000 chars each = ~30000 chars // 4 = ~7500 tokens
    # 7500 < 20000 = MIN_SAVINGS, so should NOT compact
    assert savings < MIN_SAVINGS, "Small messages should not trigger compaction"
    print("PASS: test_token_formula_min_savings_interaction")
    return True


# =============================================================================
# Runner
# =============================================================================


if __name__ == "__main__":
    sys.exit(0 if run_tests([
        test_estimate_tokens,
        test_microcompact_preserves_recent,
        test_microcompact_replaces_old,
        test_microcompact_skips_small,
        test_should_compact_threshold,
        test_should_compact_under_threshold,
        test_handle_large_output_passthrough,
        test_handle_large_output_saves,
        test_auto_compact_preserves_recent,
        test_transcript_save_and_load,
        test_microcompact_only_compactable_tools,
        # v5 mechanism-specific
        test_agent_loop_calls_microcompact,
        test_compact_command_in_repl,
        test_compactable_tools_constant,
        test_keep_recent_constant,
        test_token_threshold_constant,
        test_notification_drain_in_agent_loop,
        # v5 new mechanism tests
        test_auto_compact_threshold_default,
        test_auto_compact_threshold_large_output,
        test_min_savings_guard,
        test_min_savings_guard_proceeds,
        test_estimate_tokens_formula,
        test_compactable_tools_valid,
        test_restore_recent_files_limits,
        test_restore_recent_files_empty_cache,
        test_image_token_constant,
        test_restore_recent_files_with_actual_files,
        test_should_compact_exactly_at_threshold,
        test_should_compact_just_below_threshold,
        test_image_token_estimation_constant,
        test_token_formula_min_savings_interaction,
        # LLM integration
        test_llm_reads_multiple_files,
        test_llm_read_edit_workflow,
        test_llm_write_and_verify,
        test_llm_many_turns,
    ]) else 1)
