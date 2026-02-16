# v8: Team Messaging

**Core insight: Subagents are dispatched workers. Teammates are colleagues sitting next to you.**

v3 subagents are "divide and conquer": the main agent dispatches a task, the subagent executes, returns a result, and is destroyed. For tasks like "develop frontend and backend simultaneously," subagents are not enough: they cannot communicate with each other, cannot share progress, and are destroyed after execution.

v8 is built in three phases, each adding a layer of collaboration:

```sh
v8a: Team Foundation    - persistent teammates with lifecycle
v8b: Messaging          - file-based inboxes, 5 message types
v8c: Coordination       - shared task board, shutdown protocol, plan approval
```

## Subagent vs Teammate

| Feature | Subagent (v3) | Teammate (v8) |
|---------|--------------|---------------|
| Lifecycle | One-shot | Persistent (spawned, works, shuts down) |
| Communication | Return value (one-way) | Message protocol (two-way) |
| Parallelism | Pseudo-parallel (blocks on return) | True parallel (independent threads) |
| Task management | None | Shared Tasks (v6) |
| Use case | One-off tasks | Multi-module long-term collaboration |

---

## Phase A: Team Foundation (v8a)

### Architecture

```sh
Team Lead (main agent)
  |-- Teammate: frontend   (daemon thread)
  |-- Teammate: backend    (daemon thread)
  +-- Shared:
        |-- .tasks/         <- everyone sees the same board
        +-- .teams/         <- team config files
              +-- {team_name}/
                    +-- config.json  <- team metadata and member list
```

Each Teammate runs as a daemon thread with its own agent loop, its own context window, and runs compression (v5) independently.

### Teammate Data Model

```python
@dataclass
class Teammate:
    name: str
    team_name: str
    agent_id: str = ""       # Format: "name@team_name"
    status: str = "active"   # active | shutdown
    thread: threading.Thread
    inbox_path: Path         # .teams/{team_name}/{name}_inbox.jsonl
    color: str = ""          # ANSI color for terminal output

    def __post_init__(self):
        if not self.agent_id:
            self.agent_id = f"{self.name}@{self.team_name}"
```

The `agent_id` uses `name@team_name` (e.g. `backend@rest-to-graphql`) for identification.

### TeammateManager

```python
class TeammateManager:
    def __init__(self):
        self._teams: dict[str, dict[str, Teammate]] = {}
        self._lock = threading.Lock()
```

Three operations form the team lifecycle:
1. `create_team(name)` -- register a new team, create its directory and config.json
2. `spawn_teammate(name, team_name, prompt)` -- start a teammate thread
3. `delete_team(name)` -- send shutdown to all members, remove team

### v8a Teammate Loop (Foundation)

In v8a, the teammate loop is the simplest form: run the tool loop until done, then shut down. No inbox, no messaging:

```sh
v8a teammate:  spawn -> work (tool loop) -> shutdown (silent)
```

### TEAMMATE_TOOLS vs ALL_TOOLS

| Tool | Team Lead | Teammate |
|------|-----------|----------|
| bash, read_file, write_file, edit_file | Yes | Yes |
| TaskCreate, TaskGet, TaskUpdate, TaskList | Yes | Yes |
| SendMessage | Yes | Placeholder |
| Task (spawn subagents/teammates) | Yes | No |
| Skill | Yes | No |
| TaskOutput, TaskStop | Yes | No |
| TeamCreate, TeamDelete | Yes | No |

Teammates get base tools + task CRUD -- enough to do work, but not enough to spawn agents or manage the team.

### Task Tool: Three Modes

The same Task tool now has three modes:
1. No extra params -- synchronous subagent (v3)
2. `run_in_background=True` -- background subagent (v7)
3. `team_name + name` -- persistent teammate (v8)

---

## Phase B: Messaging (v8b)

v8b adds the inbox system so teammates can communicate.

### Message Types

| Type | Scenario | Direction |
|------|----------|-----------|
| `message` | "API docs are at docs/api.md" | Point-to-point |
| `broadcast` | "Database schema changed, everyone take note" | One-to-many |
| `shutdown_request` | "Project done, please wrap up" | Lead -> Teammate |
| `shutdown_response` | "I have wrapped up" | Teammate -> Lead |
| `plan_approval_response` | "Your refactoring plan is approved" | Lead -> Teammate |

```python
MESSAGE_TYPES = {"message", "broadcast", "shutdown_request",
                 "shutdown_response", "plan_approval_response"}
```

SendMessage requires a `summary` field (5-10 word preview) for message and broadcast types. This mirrors production behavior where summaries appear in the UI notification panel.

### Inbox Architecture

```sh
Team Lead                                  config.json
+-----------+                              +-----------+
| SendMsg() |                              | team:     |
+-----+-----+                              |  members  |
      |                                    |  config   |
      v                                    +-----------+
+------------------+
| TeammateManager  |
| .send_message()  |    point-to-point        inbox lock
|                  +----> /team/A_inbox.jsonl  (atomic writes)
| .send_message()  |
| type=broadcast   +----> /team/B_inbox.jsonl
|                  +----> /team/C_inbox.jsonl
+------------------+
                          ^
                          |
+-----------+    check_inbox() drains
| Teammate  | <-----------+
| A_inbox   |
+-----------+
```

### Team Directory Structure

```sh
.teams/
  rest-to-graphql/
    config.json             <- team metadata and member list
    frontend_inbox.jsonl    <- frontend teammate's inbox
    frontend_inbox.lock     <- lock file for atomic writes
    backend_inbox.jsonl     <- backend teammate's inbox
    backend_inbox.lock
```

### JSONL Inbox File Format

Each teammate has a dedicated inbox file at `.teams/{team_name}/{name}_inbox.jsonl`:

```json
{"type": "message", "sender": "lead", "content": "Please finish the login page first", "summary": "prioritize login page", "timestamp": 1709234567.89}
{"type": "broadcast", "sender": "backend", "content": "API schema is finalized", "summary": "API schema finalized", "timestamp": 1709234590.12}
```

Reading the inbox consumes all messages and clears the file (read-and-clear pattern).

### Inbox Lock Files

Concurrent writes are protected by lock files using `os.O_CREAT | os.O_EXCL` for atomic acquisition:

```python
def _write_to_inbox(inbox_path, message):
    lock_path = inbox_path.with_suffix(".lock")
    for _ in range(50):   # retry up to 50 times
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            time.sleep(0.05)
    try:
        with open(inbox_path, "a") as f:
            f.write(json.dumps(message) + "\n")
    finally:
        lock_path.unlink(missing_ok=True)
```

Both `_write_to_inbox` and `check_inbox` use this lock file pattern to prevent race conditions between concurrent reads and writes.

### v8b Teammate Loop (with Inbox)

```sh
v8b teammate:  spawn -> work (check inbox each turn) -> shutdown
```

The teammate checks its inbox before each API call. Messages are delivered as `<teammate-message>` XML when injected into the teammate's conversation:

```sh
<teammate-message teammate_id="{sender}" summary="{summary}">
{message text}
</teammate-message>
```

---

## Phase C: Coordination (v8c)

v8c adds the coordination layer: shared task board, shutdown protocol with request_id, plan approval, and teammate status tracking.

### Shared Task Board

```sh
Team Lead                     Shared Task Board (.tasks/)
+-----------+                 +---------------------+
| TaskCreate|+--------------->| 1.json              |
+-----------+                 | 2.json              |
                              | 3.json              |
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
```

All teammates share the same `.tasks/` directory. Task CRUD operations are thread-safe via the TaskManager's locking.

### Shutdown Protocol (with request_id)

```sh
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
```

The shutdown protocol uses `request_id` for reliable handoff:
1. Team Lead sends `shutdown_request` with a `request_id` via `SendMessage`
2. Message written to the teammate's JSONL inbox
3. Teammate reads `shutdown_request` on next inbox check
4. Teammate responds with `shutdown_response` echoing the `request_id`
5. Teammate exits its loop

### Plan Approval Flow

```sh
Teammate sends plan -> Lead reviews -> plan_approval_response
-> Teammate receives approval/rejection with feedback
```

Plan approval is a structured message type, not a tool call.

### Teammate Status Tracking

```sh
active   - currently executing tool calls
idle     - no current work (v9 adds idle polling)
shutdown - gracefully exiting
```

Status is tracked per-teammate and persisted in config.json.

### v8c Teammate Loop (Full)

```python
def _teammate_loop(self, teammate, initial_prompt):
    sub_system = f"You are teammate '{teammate.name}' in team '{teammate.team_name}'..."
    sub_messages = [{"role": "user", "content": initial_prompt}]

    while teammate.status != "shutdown":
        # Compression before each API call
        sub_messages = CTX.microcompact(sub_messages)
        if CTX.should_compact(sub_messages):
            sub_messages = CTX.auto_compact(sub_messages)

        response = client.messages.create(
            model=MODEL, system=sub_system,
            messages=sub_messages, tools=TEAMMATE_TOOLS, max_tokens=8000,
        )

        if response.stop_reason == "tool_use":
            results = [execute(tc) for tc in tool_calls]
            sub_messages.append({"role": "assistant", "content": response.content})
            sub_messages.append({"role": "user", "content": results})
            continue

        # No more tool calls -- check inbox for new instructions
        new_messages = self.check_inbox(teammate.name, teammate.team_name)
        if new_messages:
            if any(m.get("type") == "shutdown_request" for m in new_messages):
                return  # Exit
            sub_messages.append({"role": "user", "content": format(new_messages)})
            continue

        # Nothing left to do
        return
```

---

## Full Lifecycle Walkthrough

```sh
1. TeamCreate("rest-to-graphql")
   -> .teams/rest-to-graphql/ created
   -> config.json initialized

2. Task(prompt="Handle frontend", team_name="rest-to-graphql", name="frontend")
   -> Teammate spawned as daemon thread
   -> frontend_inbox.jsonl created

3. Task(prompt="Handle backend", team_name="rest-to-graphql", name="backend")
   -> Second teammate spawned

4. SendMessage(recipient="frontend", content="Use the new API schema", summary="use new API schema")
   -> Message written to frontend_inbox.jsonl (with lock)

5. Frontend teammate's loop:
   -> check_inbox() reads and clears inbox (with lock)
   -> Message injected as <teammate-message> XML
   -> Teammate processes and continues working

6. SendMessage(type="broadcast", content="Schema finalized", summary="schema finalized")
   -> Written to ALL teammate inboxes

7. TeamDelete("rest-to-graphql")
   -> shutdown_request sent to all teammates
   -> Each teammate exits on next inbox check
   -> Team removed from registry
```

## Five Conceptual Layers

```sh
+---------------------------------------------------------------+
|  Layer 5: Team Lifecycle                                      |
|    TeamCreate -> spawn teammates -> TeamDelete                 |
+---------------------------------------------------------------+
|  Layer 4: Message Protocol                                    |
|    message | broadcast | shutdown_request |                    |
|    shutdown_response | plan_approval_response                  |
|    (each with summary field + optional request_id)             |
+---------------------------------------------------------------+
|  Layer 3: Inbox System                                        |
|    .teams/{team}/{name}_inbox.jsonl                            |
|    Atomic lock files, read-and-clear pattern                   |
+---------------------------------------------------------------+
|  Layer 2: Teammate Execution                                  |
|    Daemon thread per teammate, own agent loop                  |
|    TEAMMATE_TOOLS = BASE_TOOLS + task CRUD + SendMessage       |
+---------------------------------------------------------------+
|  Layer 1: Shared State                                        |
|    Tasks (v6) on disk, Background (v7) notifications           |
+---------------------------------------------------------------+
```

## The Deeper Insight

> **From command to collaboration.**

v3 subagents follow a command pattern: the main agent gives orders, subagents obey. v8 Teammates follow a collaboration pattern: the Team Lead sets direction, Teammates work on shared tasks, communicate through inboxes.

```sh
Subagent  -> do one thing, report back            (intern)
Teammate  -> work on assigned task, communicate   (colleague)
Team Lead -> create team, assign work, coordinate (manager)
```

---

**One agent has limits. A team of agents has reach.**

[<-- v7](./v7-background-tasks.md) | [Back to README](../README.md) | [v9 -->](./v9-autonomous-teams.md)
