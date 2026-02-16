# v7: Background Tasks & Notification Bus

**Core insight: An agent that doesn't wait for results can do multiple things at once.**

v6 Tasks solved task tracking. But whether it's a subagent or a bash command, the main agent must wait during execution:

```sh
Main Agent: Task("explore codebase") -> waiting... -> got result -> continue
                                         ^
                                    can't do anything during this time
```

## Background Execution Flow

```sh
Main Thread                              Background Threads
+--------------------------+             +-------------------+
| agent_loop():            |             | Thread A (a3f7c2) |
|                          |  spawn      | func()            |
|  Task(bg=True) ---------+-----------> | ...running...     |
|  Task(bg=True) ----+    |             +-------------------+
|  Bash(bg=True) -+  |    |             +-------------------+
|                 |  |    |             | Thread B (a7b2d3) |
|  (continues     |  +--+-----------> | func()            |
|   other work)   |     |             | ...running...     |
|                 +----+-----------> +-------------------+
|                      |             +-------------------+
|                      |             | Thread C (b5e8f1) |
|                      +-----------> | func()            |
|                                    | ...running...     |
+---+----------------------+         +--------+----------+
    |                                         |
    |  drain_notifications()                  | on complete:
    |  before each API call                   |   event.set()
    v                                         |   queue.put(notif)
+---+----------------------+                  |
| Inject into messages:    | <----------------+
| attachment format:       |
| {"type": "attachment",   |
|  "attachment": {         |
|    "type":"task_status", |
|    "task_id":"a3f7c2",   |
|    "status":"completed", |
|    "summary":"Found 3.." |
|  }}                      |
+--------------------------+
```

## The Solution: Background Execution + Notifications

Two changes:

1. **Background execution**: subagents and bash can run in the background while the main agent continues
2. **Notification bus**: when background tasks complete, notifications are pushed to the main agent

```sh
Main Agent:
  Task(background) ---\
  Bash(background) ----+--- continues other work
  Task(background) ---/
                         <- notification: "Task A completed"
                         <- notification: "Command B completed"
```

## The BackgroundTask Dataclass

Each background task is tracked as a `BackgroundTask` instance:

```python
@dataclass
class BackgroundTask:
    task_id: str               # Unique ID with type prefix (e.g., "b3f7c2")
    task_type: str             # "bash" or "agent"
    thread: threading.Thread   # The daemon thread executing the work
    output: str                # Captured result (populated on completion)
    status: str                # "running" | "completed" | "error" | "stopped"
    event: threading.Event     # Signaled when task finishes, enables blocking waits
```

The `event` field is the synchronization primitive. `get_output(block=True)` calls `event.wait()` to sleep until the background thread signals completion, avoiding busy-polling.

## Background Task Types

Each background task type has a distinct ID prefix -- you know the type at a glance:

| Type | Prefix | Typical Use |
|------|--------|-------------|
| bash | `b` | Run tests, lint, build |
| agent | `a` | Explore code, analyze files |
| teammate | `t` | Teammate collaboration (v8) |

IDs are generated as `{prefix}{uuid4_hex[:6]}`, e.g. `b3a9f1` or `a7c2d4`.

## Thread Execution Model

Background tasks run in Python daemon threads (`daemon=True`). The execution wrapper:

```python
def wrapper():
    try:
        result = func()              # Execute the actual work
        bg_task.output = result
        bg_task.status = "completed"
    except Exception as e:
        bg_task.output = f"Error: {e}"
        bg_task.status = "error"      # Errors are captured, not propagated
    finally:
        output_path = self._write_output(task_id, bg_task.output)
        bg_task.event.set()           # Always signal completion
        # Matches cli.js attachment pipeline for task notifications
        self._notifications.put({
            "type": "attachment",
            "attachment": {
                "type": "task_status",
                "task_id": task_id,
                "task_type": bg_task.task_type,
                "status": bg_task.status,
                "summary": bg_task.output[:500],
                "output_file": str(output_path),
            },
        })
```

Key properties:
- **Error containment**: exceptions are caught and stored in `output`, never crashing the main agent
- **Guaranteed notification**: the `finally` block ensures a notification is always pushed
- **Daemon threads**: if the main process exits, all background threads are automatically terminated

## Triggering Background Execution

Any tool supporting `run_in_background` can run in the background:

```python
# Foreground (blocking)
Task(prompt="Analyze code")               # waits for completion

# Background (non-blocking)
Task(prompt="Analyze code", run_in_background=True)
# -> returns immediately: {"task_id": "a3f7c2", "status": "running"}
```

## Two New Tools

### TaskOutput: Read Background Task Results

```python
# Block and wait for completion
TaskOutput(task_id="a3f7c2", block=True, timeout=30000)
# -> {"status": "completed", "output": "...analysis results..."}

# Non-blocking status check
TaskOutput(task_id="a3f7c2", block=False)
# -> {"status": "running", "output": "...current output..."}
```

The `timeout` parameter (in milliseconds) prevents indefinite blocking.

### TaskStop: Terminate a Background Task

```python
TaskStop(task_id="a3f7c2")
# -> {"task_id": "a3f7c2", "status": "stopped"}
```

`stop_task` sets the status to `"stopped"` and signals the event. This is a cooperative stop -- the thread is not forcibly killed.

## Notification Drain/Inject Cycle

The notification bus is implemented as a `queue.Queue`. The main agent loop performs a **drain-and-inject** cycle before every API call. Notifications use the attachment format matching cli.js:

```python
# 1. Drain: pull all pending notifications from the queue
notifications = BG.drain_notifications()

# 2. Inject: append as attachment objects to the last user message
# Each notification is already in attachment format:
# {"type": "attachment", "attachment": {"type": "task_status", ...}}
if notifications:
    if messages[-1]["role"] == "user":
        content = messages[-1]["content"]
        if isinstance(content, list):
            content.extend(notifications)
        else:
            messages[-1]["content"] = [{"type": "text", "text": content}] + notifications
    else:
        messages.append({"role": "user", "content": notifications})
```

## Output File System

Background task outputs are saved to disk at `.task_outputs/{task_id}.output`:

```python
OUTPUT_DIR = WORKDIR / ".task_outputs"

def _write_output(self, task_id, content):
    # cli.js jSA=32000 default, configurable up to 160000 via TASK_MAX_OUTPUT_LENGTH env var
    max_output_chars = int(os.getenv("TASK_MAX_OUTPUT_LENGTH", "32000"))
    path = OUTPUT_DIR / f"{task_id}.output"
    truncated = content[:max_output_chars]
    with open(path, "a") as f:
        f.write(truncated)
    return path
```

Two purposes: large outputs don't bloat notifications, and output persists after context compression.

## Typical Flow

```sh
User: "Analyze code quality in src/ and tests/"

Main Agent:
  1. Task(background, prompt="Analyze src/")    -> task_id="a1c4e9"
  2. Task(background, prompt="Analyze tests/")  -> task_id="a7b2d3"
  3. Bash(background, command="eslint src/")     -> task_id="b5e8f1"

  (three tasks running in parallel)

  4. TaskOutput("a1c4e9", block=True)  -> wait and get result
  5. attachment notification: b5e8f1 completed  (ESLint finished while waiting)
  6. TaskOutput("a7b2d3", block=True)  -> get second result
  7. Synthesize all three results into a report
```

## Relationship with Tasks (v6)

| | Tasks (v6) | Background Tasks (v7) |
|-|-----------|----------------------|
| Purpose | Planning and tracking | Parallel execution |
| Granularity | High-level goals | Concrete execution |
| Lifecycle | Persistent across sessions | Single session |
| Visibility | Task board | Notification stream |

Tasks manage **what to do**. Background tasks manage **how to do it in parallel**.

## The Deeper Insight

> **From serial to parallel.**

The notification bus is the key glue layer: the main agent doesn't poll, completions push themselves. The "wait-execute-wait" serial pattern becomes the "launch-keep working-get notified" parallel pattern.

Background tasks lay the groundwork for v8 Teammates: a Teammate is essentially a special background task (prefix `t`), reusing the same notification and output infrastructure.

---

**Serial waiting wastes time. Parallel notification unlocks efficiency.**

[<-- v6](./v6-tasks-system.md) | [Back to README](../README.md) | [v8 -->](./v8-team-messaging.md)
