#!/usr/bin/env python3
"""
v8c_coordination.py - Mini Claude Code: Shared Task Board & Shutdown Protocol (~1500 lines)

Core Philosophy: "From Commands to Collaboration - Coordination"
=================================================================
v8a gave us teams: persistent agents with identity and lifecycle.
v8b gave us messaging: file-based inboxes with 5 message types.

v8c adds coordination: teammates can use the shared task board to
track work, the shutdown protocol uses request_id for reliable
handoff, and plan approval lets the lead review teammate plans.

    v8b teammate:  spawn -> work (check inbox each turn) -> shutdown
    v8c teammate:  spawn -> work (inbox + task board) -> shutdown

    SHARED TASK BOARD COORDINATION
    ===============================

    Team Lead                     Shared Task Board (.tasks/)
    +-----------+                 +---------------------+
    | TaskCreate|+--------------->| task_1.json         |
    +-----------+                 | task_2.json         |
                                  | task_3.json         |
    Teammate A                    +-----^-----+---------+
    +-----------+                       |     |
    | TaskGet   |+----------------------+     |
    | TaskUpdate|+----------------------------+
    +-----------+

    Teammate B
    +-----------+
    | TaskList  |+--- reads same board
    | TaskUpdate|+--- writes same board
    +-----------+

    SHUTDOWN PROTOCOL (with request_id)
    ====================================

    Lead                          Teammate
    +--------+                    +--------+
    | send   |  shutdown_request  |        |
    | msg    +---(request_id)---->| check  |
    +--------+                    | inbox  |
                                  +---+----+
                                      |
                                      v
                                  handle: set status="shutdown"
                                  respond with request_id

    PLAN APPROVAL FLOW
    ===================
    Teammate sends plan -> Lead reviews -> plan_approval_response
    -> Teammate receives approval/rejection with feedback

    TEAMMATE STATUS TRACKING
    ========================
    active   - currently executing tool calls
    idle     - no current work (v9 adds idle polling)
    shutdown - gracefully exiting

Key design details:
    - Teammates get full task CRUD: TaskCreate, TaskGet, TaskUpdate, TaskList
    - shutdown_request carries a request_id; teammate must echo it back
    - Plan approval is a structured message, not a tool call
    - Status tracked per-teammate and persisted in config.json
    - Full team lifecycle demo in main() shows create/spawn/work/delete

v9 adds: idle cycle with auto-claiming and autonomous task pickup

Usage:
    python v8c_coordination.py
"""

import json
import os
import re
import subprocess
import sys
import time
import threading
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from queue import Queue

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)


# =============================================================================
# Configuration
# =============================================================================

# When using third-party endpoints (e.g. GLM), clear ANTHROPIC_AUTH_TOKEN
# to prevent the SDK from sending a conflicting authorization header.
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TASKS_DIR = WORKDIR / ".tasks"
# cli.js stores team config at ~/.claude/teams/{name}/config.json;
# we use a local .teams/ directory for educational simplicity.
TEAMS_DIR = WORKDIR / ".teams"
OUTPUT_DIR = WORKDIR / ".task_outputs"

# Notification modes that should not be editable by the model
NON_EDITABLE_MODES = {"task-notification"}

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-5-20250929")


def is_editable(mode: str) -> bool:
    """Check whether a notification mode allows the model to edit its content."""
    return mode not in NON_EDITABLE_MODES


# =============================================================================
# TeammateManager
# =============================================================================

# ANSI colors for teammate output (cycles through for visual distinction)
TEAMMATE_COLORS = [
    "\033[36m",   # cyan
    "\033[33m",   # yellow
    "\033[35m",   # magenta
    "\033[32m",   # green
    "\033[34m",   # blue
]
COLOR_RESET = "\033[0m"

# All supported message types for the SendMessage tool
MESSAGE_TYPES = {"message", "broadcast", "shutdown_request", "shutdown_response", "plan_approval_response"}


@dataclass
class Teammate:
    name: str
    team_name: str
    agent_id: str = ""
    status: str = "active"      # active, idle, shutdown
    thread: threading.Thread = field(default=None, repr=False)
    inbox_path: Path = field(default=None)
    color: str = ""

    def __post_init__(self):
        if not self.agent_id:
            self.agent_id = f"{self.name}@{self.team_name}"


class TeammateManager:
    """
    Manages persistent agent teammates with messaging and coordination.

    Each teammate runs in its own thread with its own agent loop,
    communicates via file-based inbox, and shares the Tasks board.

    Teammates receive TEAMMATE_TOOLS (BASE_TOOLS + task CRUD + SendMessage)
    so they can update the shared task board and communicate with peers.

    Coordination features (new in v8c):
    - Shared task board: teammates can TaskCreate/TaskGet/TaskUpdate/TaskList
    - Shutdown protocol: request_id tracking for reliable handoff
    - Plan approval: lead approves/rejects teammate plans
    - Status tracking: active/idle/shutdown per teammate

    Message types:
        message              - point-to-point message to a specific teammate
        broadcast            - message to all teammates in a team
        shutdown_request     - request teammate to shut down (carries request_id)
        shutdown_response    - teammate confirms shutdown (echoes request_id)
        plan_approval_response - team lead approves/rejects a plan
    """

    def __init__(self):
        self._teams: dict[str, dict[str, Teammate]] = {}
        self._lock = threading.Lock()
        self._pending_shutdowns: dict[str, str] = {}  # request_id -> teammate_name
        TEAMS_DIR.mkdir(exist_ok=True)

    def create_team(self, name: str, description: str = "", lead_agent_id: str = "lead") -> str:
        with self._lock:
            if name in self._teams:
                return f"Team '{name}' already exists"
            self._teams[name] = {}
            team_dir = TEAMS_DIR / name
            team_dir.mkdir(exist_ok=True)
            config_path = team_dir / "config.json"
            config_path.write_text(json.dumps({
                "name": name,
                "description": description,
                "createdAt": time.time(),
                "leadAgentId": lead_agent_id,
                "members": [],
            }, indent=2))
            return f"Team '{name}' created"

    def spawn_teammate(self, name: str, team_name: str, prompt: str) -> str:
        """Spawn a persistent teammate that runs its own agent loop."""
        with self._lock:
            if team_name not in self._teams:
                return f"Error: Team '{team_name}' not found"
            if name in self._teams[team_name]:
                return f"Error: Teammate '{name}' already exists in team '{team_name}'"

            color_idx = len(self._teams[team_name]) % len(TEAMMATE_COLORS)
            inbox_path = TEAMS_DIR / team_name / f"{name}_inbox.jsonl"
            teammate = Teammate(
                name=name,
                team_name=team_name,
                inbox_path=inbox_path,
                color=TEAMMATE_COLORS[color_idx],
            )

            def run():
                self._teammate_loop(teammate, prompt)

            thread = threading.Thread(target=run, daemon=True)
            teammate.thread = thread
            self._teams[team_name][name] = teammate
            self._update_team_config(team_name)
            thread.start()

            return json.dumps({
                "name": name,
                "team": team_name,
                "agent_id": teammate.agent_id,
                "status": "active",
            })

    def _update_team_config(self, team_name: str):
        """Update config.json to reflect current team membership and status."""
        team_dir = TEAMS_DIR / team_name
        config_path = team_dir / "config.json"
        config = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
            except json.JSONDecodeError:
                pass
        config["members"] = [
            {
                "name": tm.name,
                "agentId": tm.agent_id,
                "agentType": "teammate",
                "status": tm.status,
                "joinedAt": time.time(),
            }
            for tm in self._teams.get(team_name, {}).values()
        ]
        config_path.write_text(json.dumps(config, indent=2))

    def _write_to_inbox(self, inbox_path: Path, message: dict):
        """Atomically write a message to an inbox using a lock file."""
        lock_path = inbox_path.with_suffix(".lock")
        for _ in range(50):
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                time.sleep(0.05)
        else:
            pass

        try:
            with open(inbox_path, "a") as f:
                f.write(json.dumps(message) + "\n")
        finally:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass

    def send_message(self, recipient: str, content: str, msg_type: str = "message",
                     sender: str = "lead", team_name: str = None,
                     summary: str = "", request_id: str = "") -> str:
        """Send a message to a teammate or broadcast to all teammates in a team."""
        if msg_type not in MESSAGE_TYPES:
            return f"Error: Invalid message type '{msg_type}'"

        message = {
            "type": msg_type,
            "sender": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if summary:
            message["summary"] = summary
        if request_id:
            message["request_id"] = request_id
        # Auto-generate request_id for shutdown_request if not provided
        if msg_type == "shutdown_request" and not request_id:
            auto_id = uuid.uuid4().hex[:8]
            message["request_id"] = auto_id
            self._pending_shutdowns[auto_id] = recipient

        # Broadcast: send to ALL teammates in the team, excluding sender
        if msg_type == "broadcast":
            resolved_team = team_name
            if not resolved_team:
                for tname, team in self._teams.items():
                    if sender in team or recipient in team:
                        resolved_team = tname
                        break
            if not resolved_team:
                count = 0
                for tname, team in self._teams.items():
                    for tm_name, tm in team.items():
                        if tm_name != sender:
                            self._write_to_inbox(tm.inbox_path, message)
                            count += 1
                return f"Broadcast sent to {count} teammates across all teams"

            team = self._teams.get(resolved_team, {})
            count = 0
            for tm_name, tm in team.items():
                if tm_name != sender:
                    self._write_to_inbox(tm.inbox_path, message)
                    count += 1
            return f"Broadcast sent to {count} teammates in team '{resolved_team}'"

        # Point-to-point: find the specific recipient
        teammate = self._find_teammate(recipient, team_name)
        if not teammate:
            return f"Error: Teammate '{recipient}' not found"

        self._write_to_inbox(teammate.inbox_path, message)
        return f"Message sent to {recipient}"

    def check_inbox(self, name: str, team_name: str = None) -> list:
        """Read and clear a teammate's inbox atomically using lock file."""
        teammate = self._find_teammate(name, team_name)
        if not teammate or not teammate.inbox_path:
            return []

        if not teammate.inbox_path.exists():
            return []

        lock_path = teammate.inbox_path.with_suffix(".lock")
        messages = []
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            try:
                with open(teammate.inbox_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                messages.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
                teammate.inbox_path.write_text("")
            finally:
                lock_path.unlink(missing_ok=True)
        except FileExistsError:
            pass  # Another thread holds the lock; return empty, retry next poll
        return messages

    def delete_team(self, name: str) -> str:
        """Shutdown all teammates and delete team."""
        with self._lock:
            if name not in self._teams:
                return f"Error: Team '{name}' not found"

            team = self._teams[name]
            for tm_name, teammate in team.items():
                req_id = uuid.uuid4().hex[:8]
                self.send_message(tm_name, "Team is being deleted. Please shutdown.",
                                  msg_type="shutdown_request", team_name=name,
                                  request_id=req_id)
                teammate.status = "shutdown"

            del self._teams[name]
            return f"Team '{name}' deleted, {len(team)} teammates notified"

    def get_team_status(self, team_name: str = None) -> str:
        """Get status of all teams or a specific team."""
        with self._lock:
            if team_name:
                team = self._teams.get(team_name, {})
                if not team:
                    return f"Team '{team_name}' not found or empty"
                lines = [f"Team: {team_name}"]
                for name, tm in team.items():
                    lines.append(f"  - {name}: {tm.status}")
                return "\n".join(lines)

            if not self._teams:
                return "No teams."
            lines = []
            for tname, team in self._teams.items():
                members = ", ".join(f"{n}({tm.status})" for n, tm in team.items())
                lines.append(f"Team '{tname}': {members or 'empty'}")
            return "\n".join(lines)

    def _find_teammate(self, name: str, team_name: str = None) -> Teammate:
        if team_name and team_name in self._teams:
            return self._teams[team_name].get(name)
        for team in self._teams.values():
            if name in team:
                return team[name]
        return None

    def _handle_inbox_messages(self, teammate: Teammate, messages: list, sub_messages: list) -> str:
        """Process inbox messages. Returns "shutdown" if shutdown requested, else None."""
        for msg in messages:
            msg_type = msg.get("type", "message")

            if msg_type == "shutdown_request":
                req_id = msg.get("request_id", "")
                teammate.status = "shutdown"
                # Echo back the request_id so the lead can correlate
                if req_id:
                    self.send_message(
                        msg.get("sender", "lead"),
                        f"Teammate '{teammate.name}' shutting down.",
                        msg_type="shutdown_response",
                        sender=teammate.name,
                        request_id=req_id,
                    )
                self._update_team_config(teammate.team_name)
                return "shutdown"

            if msg_type == "plan_approval_response":
                approved = msg.get("approved", False)
                feedback = msg.get("content", "")
                approval_text = "Plan APPROVED." if approved else f"Plan REJECTED: {feedback}"
                sub_messages.append({"role": "user", "content": approval_text})
                return None

        # Regular messages -- inject as user message
        msg_text = "\n".join(
            f"<teammate-message sender=\"{m.get('sender', '?')}\" type=\"{m.get('type', 'message')}\">\n"
            f"{m.get('content', '')}\n</teammate-message>"
            for m in messages
        )
        if sub_messages and sub_messages[-1].get("role") == "user":
            content = sub_messages[-1].get("content", "")
            if isinstance(content, str):
                sub_messages[-1]["content"] = content + "\n\n" + msg_text
            elif isinstance(content, list):
                content.append({"type": "text", "text": msg_text})
        else:
            sub_messages.append({"role": "user", "content": msg_text})
        return None

    def _teammate_loop(self, teammate: Teammate, initial_prompt: str):
        """
        Teammate work cycle with inbox + task board coordination.

        Processes initial prompt, checks inbox before each API call,
        handles shutdown protocol with request_id tracking. Shuts down
        when model stops calling tools or when shutdown_request received.
        No idle phase or auto-claiming -- those come in v9.
        """
        color = teammate.color
        reset = COLOR_RESET
        prefix = f"{color}[{teammate.agent_id}]{reset}"

        sub_system = f"""You are teammate '{teammate.name}' ({teammate.agent_id}) in team '{teammate.team_name}' at {WORKDIR}.

Work on your assigned tasks. Use TaskList to find tasks.
Use TaskGet to read task details before starting work.
Use TaskUpdate to mark progress. Use SendMessage to communicate with teammates.
Complete work efficiently and report results clearly."""

        sub_tools = _get_teammate_tools()
        sub_messages = [{"role": "user", "content": initial_prompt}]

        while teammate.status != "shutdown":
            teammate.status = "active"

            try:
                # Check for incoming messages before each turn
                inbox_messages = self.check_inbox(teammate.name, teammate.team_name)
                if inbox_messages:
                    handled = self._handle_inbox_messages(teammate, inbox_messages, sub_messages)
                    if handled == "shutdown":
                        return

                sub_messages = CTX.microcompact(sub_messages)
                if CTX.should_compact(sub_messages):
                    sub_messages = CTX.auto_compact(sub_messages)

                response = client.messages.create(
                    model=MODEL, system=sub_system,
                    messages=sub_messages, tools=sub_tools, max_tokens=8000,
                )

                if response.stop_reason == "tool_use":
                    tool_calls = [b for b in response.content if b.type == "tool_use"]
                    results = []
                    for tc in tool_calls:
                        output = execute_tool(tc.name, tc.input)
                        output = CTX.handle_large_output(output)
                        results.append({"type": "tool_result", "tool_use_id": tc.id, "content": output})
                    sub_messages.append({"role": "assistant", "content": response.content})
                    sub_messages.append({"role": "user", "content": results})
                    continue
                else:
                    # No more tool calls -- teammate work is done
                    teammate.status = "shutdown"
                    self._update_team_config(teammate.team_name)
                    return

            except Exception as e:
                teammate.status = "shutdown"
                self._update_team_config(teammate.team_name)
                return


TEAM_MGR = TeammateManager()


# =============================================================================
# BackgroundManager
# =============================================================================

@dataclass
class BackgroundTask:
    task_id: str
    task_type: str
    thread: threading.Thread = field(repr=False, default=None)
    output: str = ""
    status: str = "running"
    event: threading.Event = field(default_factory=threading.Event, repr=False)


class BackgroundManager:
    """
    Manages background execution of bash commands, subagents, and teammates.

    ID prefixes indicate type:
        b = bash command
        a = local agent (subagent)
        t = teammate

    When a background task completes, a notification is pushed to
    the notification queue. The main agent loop drains this queue
    before each API call, injecting notifications as user messages.
    """

    def __init__(self):
        self._tasks: dict[str, BackgroundTask] = {}
        self._notifications: Queue = Queue()
        self._lock = threading.Lock()
        OUTPUT_DIR.mkdir(exist_ok=True)

    def _gen_id(self, prefix: str) -> str:
        return f"{prefix}{uuid.uuid4().hex[:6]}"

    def _write_output(self, task_id: str, content: str) -> Path:
        """Write task output to an append-only file. Returns the file path."""
        path = OUTPUT_DIR / f"{task_id}.txt"
        with open(path, "a") as f:
            f.write(content)
        return path

    def read_output(self, task_id: str, offset: int = 0) -> str:
        """Read task output from file with optional byte offset."""
        path = OUTPUT_DIR / f"{task_id}.txt"
        if not path.exists():
            return ""
        text = path.read_text()
        return text[offset:]

    def run_in_background(self, func, task_type: str = "a") -> str:
        """
        Run a function in a background thread.
        Returns immediately with a task_id.
        """
        prefix = {"bash": "b", "agent": "a", "teammate": "t"}.get(task_type, "a")
        task_id = self._gen_id(prefix)

        bg_task = BackgroundTask(task_id=task_id, task_type=task_type)

        def wrapper():
            try:
                result = func()
                bg_task.output = result
                bg_task.status = "completed"
            except Exception as e:
                bg_task.output = f"Error: {e}"
                bg_task.status = "error"
            finally:
                output_path = self._write_output(task_id, bg_task.output)
                bg_task.event.set()
                self._notifications.put({
                    "task_id": task_id,
                    "task_type": bg_task.task_type,
                    "status": bg_task.status,
                    "summary": bg_task.output[:500],
                    "output_file": str(output_path),
                })

        thread = threading.Thread(target=wrapper, daemon=True)
        bg_task.thread = thread

        with self._lock:
            self._tasks[task_id] = bg_task

        thread.start()
        return task_id

    def get_output(self, task_id: str, block: bool = True, timeout: int = 30000) -> dict:
        """
        Get output from a background task.
        block=True waits for completion (up to timeout ms).
        """
        with self._lock:
            bg_task = self._tasks.get(task_id)

        if not bg_task:
            return {"error": f"Task {task_id} not found"}

        if block and bg_task.status == "running":
            bg_task.event.wait(timeout=timeout / 1000)

        return {
            "task_id": task_id,
            "status": bg_task.status,
            "output": bg_task.output,
        }

    def stop_task(self, task_id: str) -> dict:
        """Stop a running background task."""
        with self._lock:
            bg_task = self._tasks.get(task_id)

        if not bg_task:
            return {"error": f"Task {task_id} not found"}

        if bg_task.status == "running":
            bg_task.status = "stopped"
            bg_task.event.set()

        return {"task_id": task_id, "status": "stopped"}

    def drain_notifications(self) -> list:
        """Drain all pending notifications from the queue."""
        notifications = []
        while not self._notifications.empty():
            try:
                notifications.append(self._notifications.get_nowait())
            except Exception:
                break
        return notifications


BG = BackgroundManager()


# =============================================================================
# TaskManager (from v6)
# =============================================================================

@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str = "pending"
    active_form: str = ""
    owner: str = ""
    blocks: list = field(default_factory=list)
    blocked_by: list = field(default_factory=list)


class TaskManager:
    """
    File-based task management with dependency tracking.

    Each task is a JSON file in .tasks/ directory. Thread-level locking
    ensures safety when multiple agents (lead, subagents, teammates)
    access the same tasks concurrently.
    """

    def __init__(self, tasks_dir: Path = None):
        self.tasks_dir = tasks_dir or TASKS_DIR
        self.tasks_dir.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self._counter = self._load_counter()

    def _load_counter(self) -> int:
        existing = list(self.tasks_dir.glob("task_*.json"))
        if not existing:
            return 1
        ids = []
        for f in existing:
            try:
                ids.append(int(f.stem.split("_")[1]))
            except (ValueError, IndexError):
                pass
        return max(ids) + 1 if ids else 1

    def _task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"task_{task_id}.json"

    def _save_task(self, task: Task):
        self._task_path(task.id).write_text(json.dumps(asdict(task), indent=2))

    def _load_task(self, task_id: str) -> Task:
        path = self._task_path(task_id)
        if not path.exists():
            return None
        return Task(**json.loads(path.read_text()))

    def create(self, subject: str, description: str = "", active_form: str = "") -> Task:
        with self._lock:
            task = Task(
                id=str(self._counter),
                subject=subject,
                description=description,
                active_form=active_form or f"Working on: {subject}",
            )
            self._counter += 1
            self._save_task(task)
            return task

    def get(self, task_id: str) -> Task:
        return self._load_task(task_id)

    def update(self, task_id: str, **kwargs) -> Task:
        with self._lock:
            task = self._load_task(task_id)
            if not task:
                return None

            for key in ("status", "subject", "description", "active_form", "owner"):
                if key in kwargs:
                    setattr(task, key, kwargs[key])

            if "addBlocks" in kwargs:
                for blocked_id in kwargs["addBlocks"]:
                    if blocked_id not in task.blocks:
                        task.blocks.append(blocked_id)
                    blocked_task = self._load_task(blocked_id)
                    if blocked_task and task.id not in blocked_task.blocked_by:
                        blocked_task.blocked_by.append(task.id)
                        self._save_task(blocked_task)

            if "addBlockedBy" in kwargs:
                for blocker_id in kwargs["addBlockedBy"]:
                    if blocker_id not in task.blocked_by:
                        task.blocked_by.append(blocker_id)
                    blocker_task = self._load_task(blocker_id)
                    if blocker_task and task.id not in blocker_task.blocks:
                        blocker_task.blocks.append(task.id)
                        self._save_task(blocker_task)

            if kwargs.get("status") == "completed":
                self._clear_dependency(task.id)

            self._save_task(task)
            return task

    def _clear_dependency(self, completed_id: str):
        for path in self.tasks_dir.glob("task_*.json"):
            try:
                data = json.loads(path.read_text())
                if completed_id in data.get("blocked_by", []):
                    data["blocked_by"].remove(completed_id)
                    path.write_text(json.dumps(data, indent=2))
            except (json.JSONDecodeError, KeyError):
                pass

    def list_all(self) -> list:
        tasks = []
        for path in sorted(self.tasks_dir.glob("task_*.json")):
            try:
                tasks.append(Task(**json.loads(path.read_text())))
            except (json.JSONDecodeError, KeyError):
                pass
        return tasks

    def delete(self, task_id: str) -> bool:
        path = self._task_path(task_id)
        if path.exists():
            path.unlink()
            return True
        return False


TASK_MGR = TaskManager()


# =============================================================================
# ContextManager (from v5)
# =============================================================================

def auto_compact_threshold(context_window: int = 200000, max_output: int = 16384) -> int:
    """Dynamic threshold: context_window - min(max_output, 20000) - 13000.
    For a 200K window with 16K output: 200000 - 16384 - 13000 = 170616."""
    output_reserve = min(max_output, 20000)
    return context_window - output_reserve - 13000


MIN_SAVINGS = 20000
MAX_RESTORE_FILES = 5
MAX_RESTORE_TOKENS_PER_FILE = 5000
MAX_RESTORE_TOKENS_TOTAL = 50000
IMAGE_TOKEN_ESTIMATE = 2000


class ContextManager:
    """
    Three-layer context compression to keep conversations within window limits.

    Human working memory is limited too - we don't remember every line of code
    we wrote, just "what we did, why, and current state". Compression mimics
    this cognitive pattern:
    - Micro-compact = short-term memory auto-decay
    - Auto-compact  = detail memory -> concept memory
    - Disk transcript = long-term memory archive
    """

    # Matches cli.js $UY set of compactable tool types
    COMPACTABLE_TOOLS = {"bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir", "notebook_edit"}
    KEEP_RECENT = 3
    TOKEN_THRESHOLD = auto_compact_threshold()
    MAX_OUTPUT_TOKENS = 40000

    def __init__(self, max_context_tokens: int = 200000):
        self.max_context_tokens = max_context_tokens
        TRANSCRIPT_DIR.mkdir(exist_ok=True)

    @staticmethod
    def estimate_tokens(text: str) -> int:
        # cli.js H2: Math.round(A.length / q) with default divisor q=4
        # Production cli.js also applies a 1.333x multiplier (Wp1) for
        # message-level counting. Omitted here for teaching clarity.
        return len(text) // 4

    def microcompact(self, messages: list) -> list:
        """
        Layer 1: Replace old large tool outputs with placeholders.

        Keeps the tool call structure intact - the model still knows WHAT
        it called, just can't see the old output. It can re-read if needed.
        Only applies clearing if total estimated savings >= MIN_SAVINGS.
        """
        tool_result_indices = []

        for i, msg in enumerate(messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for j, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_name = self._find_tool_name(messages, block.get("tool_use_id", ""))
                    if tool_name in self.COMPACTABLE_TOOLS:
                        tool_result_indices.append((i, j, block))

        # Keep only the most recent KEEP_RECENT, compact the rest
        to_compact = tool_result_indices[:-self.KEEP_RECENT] if len(tool_result_indices) > self.KEEP_RECENT else []

        # Estimate total savings before clearing; skip if below threshold
        estimated_savings = 0
        clearable = []
        for i, j, block in to_compact:
            content_str = block.get("content", "")
            if isinstance(content_str, str) and self.estimate_tokens(content_str) > 1000:
                estimated_savings += self.estimate_tokens(content_str)
                clearable.append(block)

        if estimated_savings >= MIN_SAVINGS:
            for block in clearable:
                # Matches cli.js wJA replacement string
                block["content"] = "[Old tool result content cleared]"

        return messages

    def should_compact(self, messages: list) -> bool:
        """Check if context is approaching the window limit."""
        total = sum(self.estimate_tokens(json.dumps(m, default=str)) for m in messages)
        return total > self.TOKEN_THRESHOLD

    def auto_compact(self, messages: list) -> list:
        """
        Layer 2: Summarize entire conversation, replace ALL messages.

        Production cli.js auto_compact replaces the ENTIRE message list with:
        [user_summary_message, assistant_ack, ...restored_file_messages].
        There is no "keep last N messages" behavior in auto_compact.
        Only manual /compact can optionally preserve messages.

        1. Save full transcript to disk (never lose data)
        2. Call model to generate chronological summary
        3. Replace all messages with summary + restored files
        """
        self.save_transcript(messages)

        # Capture file access history before compaction
        restored_files = self.restore_recent_files(messages)

        conversation_text = self._messages_to_text(messages)

        summary_response = client.messages.create(
            model=MODEL,
            system="You are a conversation summarizer. Be concise but thorough.",
            messages=[{
                "role": "user",
                "content": f"Summarize this conversation chronologically. Include: goals, actions taken, decisions made, current state, and pending work.\n\n{conversation_text[:100000]}"
            }],
            max_tokens=2000,
        )

        summary = summary_response.content[0].text

        # Replace ALL messages with summary + restored files (no "keep last N")
        result = [
            {"role": "user", "content": f"[Conversation compressed]\n\n{summary}"},
            {"role": "assistant", "content": "Understood. I have the context from the compressed conversation. Continuing work."},
        ]
        # Interleave restored files as user/assistant pairs to maintain valid turn order
        for rf in restored_files:
            result.append(rf)
            result.append({"role": "assistant", "content": "Noted, file content restored."})
        return result

    def handle_large_output(self, output: str) -> str:
        """
        Handle oversized tool output: save to disk, return preview.
        """
        if self.estimate_tokens(output) <= self.MAX_OUTPUT_TOKENS:
            return output

        filename = f"output_{int(time.time())}.txt"
        path = TRANSCRIPT_DIR / filename
        path.write_text(output)

        preview = output[:2000]
        return f"Output too large ({self.estimate_tokens(output)} tokens). Saved to: {path}\n\nPreview:\n{preview}..."

    def save_transcript(self, messages: list):
        """Append full transcript to disk. The permanent archive."""
        path = TRANSCRIPT_DIR / "transcript.jsonl"
        with open(path, "a") as f:
            for msg in messages:
                f.write(json.dumps(msg, default=str) + "\n")

    def restore_recent_files(self, messages: list) -> list:
        """After auto-compact, re-inject recently-read files into context.
        Scans conversation history for read_file calls and returns restoration
        messages for the most recently accessed files within token limits."""
        file_cache = {}
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("name") == "read_file":
                    path = block.get("input", {}).get("path", "")
                    if path:
                        file_cache[path] = len(file_cache)
                elif hasattr(block, "name") and block.name == "read_file":
                    path = getattr(block, "input", {}).get("path", "")
                    if path:
                        file_cache[path] = len(file_cache)

        restored = []
        total_tokens = 0
        # Sort by access order (most recent last -> reverse for most recent first)
        sorted_paths = sorted(file_cache.keys(), key=lambda p: file_cache[p], reverse=True)
        for path in sorted_paths[:MAX_RESTORE_FILES]:
            try:
                full_path = (WORKDIR / path).resolve()
                if not full_path.is_relative_to(WORKDIR) or not full_path.exists():
                    continue
                content = full_path.read_text()
                tokens = self.estimate_tokens(content)
                if tokens > MAX_RESTORE_TOKENS_PER_FILE:
                    continue
                if total_tokens + tokens > MAX_RESTORE_TOKENS_TOTAL:
                    break
                restored.append({
                    "role": "user",
                    "content": f"[Restored after compact] {path}:\n{content}"
                })
                total_tokens += tokens
            except (OSError, ValueError):
                continue
        return restored

    def _find_tool_name(self, messages: list, tool_use_id: str) -> str:
        """Find tool name from a tool_use_id in message history."""
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "id") and block.id == tool_use_id:
                        return block.name
                    if isinstance(block, dict) and block.get("id") == tool_use_id:
                        return block.get("name", "")
        return ""

    def _messages_to_text(self, messages: list) -> str:
        """Convert messages to plain text for summarization."""
        lines = []
        for msg in messages:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, str):
                lines.append(f"[{role}] {content[:500]}")
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_result":
                            text = str(block.get("content", ""))[:200]
                            lines.append(f"[tool_result] {text}")
                        elif block.get("type") == "text":
                            lines.append(f"[{role}] {block.get('text', '')[:500]}")
                    elif hasattr(block, "text"):
                        lines.append(f"[{role}] {block.text[:500]}")
        return "\n".join(lines)


CTX = ContextManager()


# =============================================================================
# SkillLoader (from v4)
# =============================================================================

class SkillLoader:
    """Loads and manages skills from SKILL.md files."""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills = {}
        self.load_skills()

    def parse_skill_md(self, path: Path) -> dict:
        content = path.read_text()
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if not match:
            return None
        frontmatter, body = match.groups()
        metadata = {}
        for line in frontmatter.strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip("\"'")
        if "name" not in metadata or "description" not in metadata:
            return None
        return {"name": metadata["name"], "description": metadata["description"], "body": body.strip(), "path": path, "dir": path.parent}

    def load_skills(self):
        if not self.skills_dir.exists():
            return
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            skill = self.parse_skill_md(skill_md)
            if skill:
                self.skills[skill["name"]] = skill

    def get_descriptions(self) -> str:
        if not self.skills:
            return "(no skills available)"
        return "\n".join(f"- {name}: {skill['description']}" for name, skill in self.skills.items())

    def get_skill_content(self, name: str) -> str:
        if name not in self.skills:
            return None
        skill = self.skills[name]
        content = f"# Skill: {skill['name']}\n\n{skill['body']}"
        resources = []
        for folder, label in [("scripts", "Scripts"), ("references", "References"), ("assets", "Assets")]:
            folder_path = skill["dir"] / folder
            if folder_path.exists():
                files = list(folder_path.glob("*"))
                if files:
                    resources.append(f"{label}: {', '.join(f.name for f in files)}")
        if resources:
            content += f"\n\n**Available resources in {skill['dir']}:**\n" + "\n".join(f"- {r}" for r in resources)
        return content

    def list_skills(self) -> list:
        return list(self.skills.keys())


SKILLS = SkillLoader(SKILLS_DIR)


# =============================================================================
# Agent Type Registry (from v3)
# =============================================================================

AGENT_TYPES = {
    "explore": {
        "description": "Read-only agent for exploring code, finding files, searching",
        "tools": ["bash", "read_file"],
        "prompt": "You are an exploration agent. Search and analyze, but never modify files. Return a concise summary.",
    },
    "code": {
        "description": "Full agent for implementing features and fixing bugs",
        "tools": "*",
        "prompt": "You are a coding agent. Implement the requested changes efficiently.",
    },
    "plan": {
        "description": "Planning agent for designing implementation strategies",
        "tools": ["bash", "read_file"],
        "prompt": "You are a planning agent. Analyze the codebase and output a numbered implementation plan. Do NOT make changes.",
    },
}


def get_agent_descriptions() -> str:
    return "\n".join(f"- {name}: {cfg['description']}" for name, cfg in AGENT_TYPES.items())


# =============================================================================
# System Prompt (team lead focused)
# =============================================================================

SYSTEM = f"""You are a coding agent (Team Lead) at {WORKDIR}.

Loop: plan -> act with tools -> report.

**Skills available** (invoke with Skill tool when task matches):
{SKILLS.get_descriptions()}

**Subagents available** (invoke with Task tool for focused subtasks):
{get_agent_descriptions()}

**Teammate system:**
- Use TeamCreate to form a team for persistent collaboration
- Spawn teammates via Task with team_name + name parameters
- Teammates work independently in background threads
- Communicate via SendMessage (point-to-point or broadcast)
- Everyone shares the same task board (TaskCreate/TaskUpdate/TaskList)
- Send shutdown_request to gracefully stop a teammate

You can run tasks in background with run_in_background=true on Task/bash tools.
Use TaskOutput to check results. Notifications arrive automatically when background tasks complete.

Rules:
- Use TeamCreate for tasks needing parallel collaboration
- Use TaskCreate/TaskUpdate to track multi-step work
- Use SendMessage to communicate with teammates
- Prefer tools over prose. Act, don't just explain.
- After finishing, summarize what changed."""


# =============================================================================
# Tool Definitions
# =============================================================================

BASE_TOOLS = [
    {"name": "bash", "description": "Run shell command. Set run_in_background=true for background execution.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}, "run_in_background": {"type": "boolean"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
]

SUBAGENT_TOOL = {
    "name": "Task",
    "description": f"Spawn a subagent or teammate.\n\nAgent types:\n{get_agent_descriptions()}\n\nAdd team_name + name to spawn a persistent teammate instead of a one-shot subagent.",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Short task description"},
            "prompt": {"type": "string", "description": "Detailed instructions"},
            "agent_type": {"type": "string", "enum": list(AGENT_TYPES.keys())},
            "run_in_background": {"type": "boolean"},
            "team_name": {"type": "string", "description": "Team name to spawn as teammate"},
            "name": {"type": "string", "description": "Teammate name (required with team_name)"},
        },
        "required": ["description", "prompt", "agent_type"],
    },
}

SKILL_TOOL = {
    "name": "Skill",
    "description": f"Load a skill for specialized knowledge.\n\nAvailable:\n{SKILLS.get_descriptions()}",
    "input_schema": {"type": "object", "properties": {"skill": {"type": "string"}}, "required": ["skill"]},
}

# Task CRUD tools (from v6)
TASK_CREATE_TOOL = {
    "name": "TaskCreate", "description": "Create a new task to track work.",
    "input_schema": {"type": "object", "properties": {
        "subject": {"type": "string"}, "description": {"type": "string"}, "activeForm": {"type": "string"},
    }, "required": ["subject", "description"]},
}

TASK_GET_TOOL = {
    "name": "TaskGet", "description": "Get task details by ID.",
    "input_schema": {"type": "object", "properties": {"taskId": {"type": "string"}}, "required": ["taskId"]},
}

TASK_UPDATE_TOOL = {
    "name": "TaskUpdate", "description": "Update a task: status, dependencies, owner.",
    "input_schema": {"type": "object", "properties": {
        "taskId": {"type": "string"},
        "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "deleted"]},
        "addBlockedBy": {"type": "array", "items": {"type": "string"}},
        "addBlocks": {"type": "array", "items": {"type": "string"}},
        "owner": {"type": "string"},
    }, "required": ["taskId"]},
}

TASK_LIST_TOOL = {
    "name": "TaskList", "description": "List all tasks with status and dependencies.",
    "input_schema": {"type": "object", "properties": {}},
}

# Background task management tools
TASK_OUTPUT_TOOL = {
    "name": "TaskOutput", "description": "Get output from a background task. block=true to wait for completion.",
    "input_schema": {"type": "object", "properties": {
        "task_id": {"type": "string"},
        "block": {"type": "boolean", "default": True},
        "timeout": {"type": "integer", "default": 30000},
    }, "required": ["task_id"]},
}

TASK_STOP_TOOL = {
    "name": "TaskStop", "description": "Stop a running background task.",
    "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
}

# Teammate tools
TEAM_CREATE_TOOL = {
    "name": "TeamCreate", "description": "Create a team for persistent collaboration.",
    "input_schema": {"type": "object", "properties": {"name": {"type": "string", "description": "Team name"}}, "required": ["name"]},
}

SEND_MESSAGE_TOOL = {
    "name": "SendMessage",
    "description": "Send a message to a teammate, or broadcast to all teammates in a team.",
    "input_schema": {"type": "object", "properties": {
        "recipient": {"type": "string", "description": "Teammate name (or any name for broadcast)"},
        "content": {"type": "string"},
        "type": {"type": "string", "enum": list(MESSAGE_TYPES), "default": "message"},
        "summary": {"type": "string", "description": "5-10 word preview (required for message/broadcast)"},
        "request_id": {"type": "string", "description": "Correlation ID for shutdown protocol"},
        "team_name": {"type": "string", "description": "Team name (required for broadcast)"},
    }, "required": ["recipient", "content"]},
}

TEAM_DELETE_TOOL = {
    "name": "TeamDelete", "description": "Shutdown and delete a team.",
    "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
}

# Teammate tools: base tools + task CRUD (including TaskGet) + messaging
TEAMMATE_TOOLS = BASE_TOOLS + [TASK_CREATE_TOOL, TASK_GET_TOOL, TASK_UPDATE_TOOL, TASK_LIST_TOOL, SEND_MESSAGE_TOOL]

# Lead agent tools: everything
ALL_TOOLS = BASE_TOOLS + [
    SUBAGENT_TOOL, SKILL_TOOL,
    TASK_CREATE_TOOL, TASK_GET_TOOL, TASK_UPDATE_TOOL, TASK_LIST_TOOL,
    TASK_OUTPUT_TOOL, TASK_STOP_TOOL,
    TEAM_CREATE_TOOL, SEND_MESSAGE_TOOL, TEAM_DELETE_TOOL,
]


def get_tools_for_agent(agent_type: str) -> list:
    """Get tools for a one-shot subagent based on its type."""
    allowed = AGENT_TYPES.get(agent_type, {}).get("tools", "*")
    if allowed == "*":
        return BASE_TOOLS
    return [t for t in BASE_TOOLS if t["name"] in allowed]


def _get_teammate_tools() -> list:
    """Get tools for a persistent teammate (base + tasks + messaging)."""
    return TEAMMATE_TOOLS


# =============================================================================
# Tool Implementations
# =============================================================================

def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(cmd: str, background: bool = False) -> str:
    if any(d in cmd for d in ["rm -rf /", "sudo", "shutdown"]):
        return "Error: Dangerous command"

    if background:
        task_id = BG.run_in_background(lambda: _exec_bash(cmd), task_type="bash")
        return json.dumps({"task_id": task_id, "status": "running"})

    return _exec_bash(cmd)


def _exec_bash(cmd: str) -> str:
    try:
        r = subprocess.run(cmd, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=120)
        return ((r.stdout + r.stderr).strip() or "(no output)")[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit:
            lines = lines[:limit]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        text = fp.read_text()
        if old_text not in text:
            return f"Error: Text not found in {path}"
        fp.write_text(text.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def run_skill(skill_name: str) -> str:
    content = SKILLS.get_skill_content(skill_name)
    if content is None:
        return f"Error: Unknown skill '{skill_name}'. Available: {', '.join(SKILLS.list_skills()) or 'none'}"
    return f'<skill-loaded name="{skill_name}">\n{content}\n</skill-loaded>\n\nFollow the instructions above.'


def run_subagent(description: str, prompt: str, agent_type: str,
                 background: bool = False, team_name: str = None, name: str = None) -> str:
    if agent_type not in AGENT_TYPES:
        return f"Error: Unknown agent type '{agent_type}'"

    # If team_name + name provided, spawn as persistent teammate
    if team_name and name:
        return TEAM_MGR.spawn_teammate(name, team_name, prompt)

    if background:
        task_id = BG.run_in_background(
            lambda: _exec_subagent(description, prompt, agent_type),
            task_type="agent"
        )
        return json.dumps({"task_id": task_id, "status": "running"})

    return _exec_subagent(description, prompt, agent_type)


def _exec_subagent(description: str, prompt: str, agent_type: str) -> str:
    config = AGENT_TYPES[agent_type]
    sub_system = f"You are a {agent_type} subagent at {WORKDIR}.\n\n{config['prompt']}\n\nComplete the task and return a concise summary."
    sub_tools = get_tools_for_agent(agent_type)
    sub_messages = [{"role": "user", "content": prompt}]

    while True:
        sub_messages = CTX.microcompact(sub_messages)
        if CTX.should_compact(sub_messages):
            sub_messages = CTX.auto_compact(sub_messages)

        response = client.messages.create(model=MODEL, system=sub_system, messages=sub_messages, tools=sub_tools, max_tokens=8000)
        if response.stop_reason != "tool_use":
            break

        results = []
        for tc in [b for b in response.content if b.type == "tool_use"]:
            output = execute_tool(tc.name, tc.input)
            output = CTX.handle_large_output(output)
            results.append({"type": "tool_result", "tool_use_id": tc.id, "content": output})

        sub_messages.append({"role": "assistant", "content": response.content})
        sub_messages.append({"role": "user", "content": results})

    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return "(subagent returned no text)"


def run_task_create(subject: str, description: str = "", active_form: str = "") -> str:
    task = TASK_MGR.create(subject, description, active_form)
    return json.dumps({"id": task.id, "subject": task.subject, "status": task.status})


def run_task_get(task_id: str) -> str:
    task = TASK_MGR.get(task_id)
    if not task:
        return f"Error: Task {task_id} not found"
    return json.dumps(asdict(task), indent=2)


def run_task_update(task_id: str, **kwargs) -> str:
    if kwargs.get("status") == "deleted":
        if TASK_MGR.delete(task_id):
            return f"Task {task_id} deleted"
        return f"Error: Task {task_id} not found"
    task = TASK_MGR.update(task_id, **kwargs)
    if not task:
        return f"Error: Task {task_id} not found"
    return json.dumps({"id": task.id, "status": task.status, "blocked_by": task.blocked_by})


def run_task_list() -> str:
    tasks = TASK_MGR.list_all()
    if not tasks:
        return "No tasks."
    lines = []
    for t in tasks:
        icon = {"completed": "[x]", "in_progress": "[>]"}.get(t.status, "[ ]")
        blocked = f" (blocked by: {', '.join(t.blocked_by)})" if t.blocked_by else ""
        owner = f" @{t.owner}" if t.owner else ""
        lines.append(f"#{t.id}. {icon} {t.subject}{blocked}{owner}")
    return "\n".join(lines)


def execute_tool(name: str, args: dict) -> str:
    if name == "bash":
        return run_bash(args["command"], args.get("run_in_background", False))
    if name == "read_file":
        return run_read(args["path"], args.get("limit"))
    if name == "write_file":
        return run_write(args["path"], args["content"])
    if name == "edit_file":
        return run_edit(args["path"], args["old_text"], args["new_text"])
    if name == "Task":
        return run_subagent(
            args["description"], args["prompt"], args["agent_type"],
            args.get("run_in_background", False),
            args.get("team_name"), args.get("name"),
        )
    if name == "Skill":
        return run_skill(args["skill"])
    if name == "TaskCreate":
        return run_task_create(args["subject"], args.get("description", ""), args.get("activeForm", ""))
    if name == "TaskGet":
        return run_task_get(args["taskId"])
    if name == "TaskUpdate":
        kw = {k: v for k, v in args.items() if k != "taskId"}
        return run_task_update(args["taskId"], **kw)
    if name == "TaskList":
        return run_task_list()
    if name == "TaskOutput":
        result = BG.get_output(args["task_id"], args.get("block", True), args.get("timeout", 30000))
        return json.dumps(result)
    if name == "TaskStop":
        result = BG.stop_task(args["task_id"])
        return json.dumps(result)
    if name == "TeamCreate":
        return TEAM_MGR.create_team(args["name"])
    if name == "SendMessage":
        return TEAM_MGR.send_message(
            args["recipient"], args["content"],
            args.get("type", "message"),
            sender=args.get("sender", "lead"),
            team_name=args.get("team_name"),
            summary=args.get("summary", ""),
            request_id=args.get("request_id", ""),
        )
    if name == "TeamDelete":
        return TEAM_MGR.delete_team(args["name"])
    return f"Unknown tool: {name}"


# =============================================================================
# Main Agent Loop - with background task notifications
# =============================================================================

def agent_loop(messages: list) -> list:
    while True:
        messages = CTX.microcompact(messages)
        if CTX.should_compact(messages):
            print("\n[Compressing context...]")
            messages = CTX.auto_compact(messages)
            print("[Context compressed.]\n")

        # Drain background task notifications and inject before API call
        notifications = BG.drain_notifications()
        if notifications:
            notif_text = "\n".join(
                f"<task-notification>\n"
                f"  <task-id>{n['task_id']}</task-id>\n"
                f"  <task-type>{n.get('task_type', 'unknown')}</task-type>\n"
                f"  <status>{n['status']}</status>\n"
                f"  <summary>{n['summary']}</summary>\n"
                f"  <output-file>{n.get('output_file', '')}</output-file>\n"
                f"</task-notification>"
                for n in notifications
            )
            if messages and messages[-1].get("role") == "user":
                content = messages[-1].get("content", "")
                if isinstance(content, str):
                    messages[-1]["content"] = content + "\n\n" + notif_text
                elif isinstance(content, list):
                    content.append({"type": "text", "text": notif_text})
            else:
                messages.append({"role": "user", "content": notif_text})

        response = client.messages.create(model=MODEL, system=SYSTEM, messages=messages, tools=ALL_TOOLS, max_tokens=8000)

        tool_calls = []
        for block in response.content:
            if hasattr(block, "text"):
                print(block.text)
            if block.type == "tool_use":
                tool_calls.append(block)

        if response.stop_reason != "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            return messages

        results = []
        for tc in tool_calls:
            if tc.name == "Task":
                bg = tc.input.get("run_in_background", False)
                tm = tc.input.get("team_name")
                label = f"Task(teammate:{tc.input.get('name', '?')})" if tm else f"Task{'(bg)' if bg else ''}"
                print(f"\n> {label}: {tc.input.get('description', 'subtask')}")
            elif tc.name == "Skill":
                print(f"\n> Loading skill: {tc.input.get('skill', '?')}")
            elif tc.name in ("TaskOutput", "TaskStop"):
                print(f"\n> {tc.name}: {tc.input.get('task_id', '')}")
            elif tc.name in ("TeamCreate", "TeamDelete"):
                print(f"\n> {tc.name}: {tc.input.get('name', '')}")
            elif tc.name == "SendMessage":
                print(f"\n> SendMessage -> {tc.input.get('recipient', '?')} ({tc.input.get('type', 'message')})")
            elif tc.name.startswith("Task"):
                print(f"\n> {tc.name}: {tc.input.get('subject', tc.input.get('taskId', ''))}")
            else:
                bg = tc.input.get("run_in_background", False) if tc.name == "bash" else False
                print(f"\n> {tc.name}{'(bg)' if bg else ''}")

            output = execute_tool(tc.name, tc.input)
            output = CTX.handle_large_output(output)

            if tc.name == "Skill":
                print(f"  Skill loaded ({len(output)} chars)")
            elif tc.name != "Task" or tc.input.get("run_in_background") or tc.input.get("team_name"):
                preview = output[:200] + "..." if len(output) > 200 else output
                print(f"  {preview}")

            results.append({"type": "tool_result", "tool_use_id": tc.id, "content": output})

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": results})


# =============================================================================
# Main REPL
# =============================================================================

def main():
    print(f"Mini Claude Code v8c (Team Coordination) - {WORKDIR}")
    print(f"Skills: {', '.join(SKILLS.list_skills()) or 'none'}")
    print("Commands: /compact, /tasks, /team, exit")
    print()

    history = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input or user_input.lower() in ("exit", "quit", "q"):
            break

        if user_input.strip() == "/compact":
            if history:
                print("[Manual compression...]")
                history = CTX.auto_compact(history)
                print("[Done.]\n")
            else:
                print("[Nothing to compress.]\n")
            continue

        if user_input.strip() == "/tasks":
            print(run_task_list())
            print()
            continue

        if user_input.strip() == "/team":
            print(TEAM_MGR.get_team_status())
            print()
            continue

        history.append({"role": "user", "content": user_input})

        try:
            agent_loop(history)
        except Exception as e:
            print(f"Error: {e}")

        print()


if __name__ == "__main__":
    main()
