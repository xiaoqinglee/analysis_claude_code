# v6: Tasks System

**Core insight: From personal sticky notes to team kanban.**

v2 introduced TodoWrite to solve "the model forgets its plan." But with compression (v5) and subagents (v3), TodoWrite's limitations are exposed.

## The Problem

```sh
TodoWrite limitations:
  1. Write-only with overwrite (sends entire list each time)
  2. No persistence (lost after compression)
  3. No ownership (who is working on this?)
  4. No dependencies (A must complete before B)
  5. No concurrency safety (two agents writing = data loss)
```

v5 compression clears in-memory todos. Subagents can't share tasks. The Tasks system redesigns task management from scratch.

## TodoWrite vs Tasks

| Feature | TodoWrite (v2) | Tasks (v6) |
|---------|---------------|------------|
| Operations | Overwrite | CRUD (create/read/update/delete) |
| Persistence | Memory only (lost on compact) | Disk files (survives compact) |
| Concurrency | Unsafe | Thread-level locking (in-process threading.Lock; production uses file-based locks via proper-lockfile) |
| Dependencies | None | blocks / blockedBy |
| Ownership | None | Agent name |
| Multi-agent | Not supported | Native support |

## Task State Machine with Dependency Auto-Clear

```sh
+--------+     update(status)     +-------------+     update(status)     +-----------+
| pending| ------------------->   | in_progress | ------------------->   | completed |
+--------+                        +-------------+                        +-----+-----+
    ^                                    |                                     |
    |          update(status)            |                                     |
    +------------------------------------+                                     |
                (re-open)                                                      |
                                                                               |
  Any state ---> deleted (file is physically deleted from disk)                                   |
                                                                               |
  On completion, auto-clear dependency:                                        |
  +---------------------------------------------------------------------------+
  |
  v
  for each task T where T.blocked_by contains completed_id:
      T.blocked_by.remove(completed_id)
      if T.blocked_by is now empty:
          T becomes executable
```

When a task transitions to `completed`, `_clear_dependency()` scans all other tasks and removes the completed task ID from their `blocked_by` lists. This makes downstream tasks automatically executable.

## Data Model

```python
@dataclass
class Task:
    id: str              # Highwatermark auto-increment ID
    subject: str         # Imperative title: "Fix auth bug"
    description: str     # Detailed description
    status: str = "pending"  # pending | in_progress | completed
    active_form: str = ""    # Present participle: "Fixing auth bug"
    owner: str = ""          # Responsible agent
    blocks: list = []        # Tasks blocked by this one
    blocked_by: list = []    # Prerequisites blocking this task
```

## Highwatermark ID Allocation

Task IDs use a counter that only goes up. The counter is persisted to a `.highwatermark` file and falls back to scanning existing task files on startup:

```python
HIGHWATERMARK_FILE = ".highwatermark"

def _load_counter(self):
    hwm_path = self.tasks_dir / HIGHWATERMARK_FILE
    if hwm_path.exists():
        try:
            return int(hwm_path.read_text().strip()) + 1
        except ValueError:
            pass
    existing = list(self.tasks_dir.glob("*.json"))
    if not existing:
        return 1
    ids = []
    for f in existing:
        try:
            ids.append(int(f.stem))
        except ValueError:
            pass
    return max(ids) + 1 if ids else 1
```

This prevents ID reuse if tasks are deleted. IDs are monotonically increasing.

## Four CRUD Tools

```python
# TaskCreate: create a task
TaskCreate("Fix auth bug", description="...", activeForm="Fixing auth bug")
# -> {"id": "1", "subject": "Fix auth bug"}

# TaskGet: read details
TaskGet("1")
# -> {id, subject, description, status, blocks, blockedBy}

# TaskUpdate: update status, dependencies, owner
TaskUpdate("1", status="in_progress")
TaskUpdate("2", addBlockedBy=["1"])    # 2 depends on 1

# TaskList: list all tasks
TaskList()
# -> #1. [>] Fix auth bug  @agent
#    #2. [ ] Write tests   blocked by: #1
```

## Dependency Graph

```sh
TaskCreate: "Set up database"       -> #1
TaskCreate: "Write API endpoints"   -> #2
TaskCreate: "Write tests"           -> #3

TaskUpdate: id=2, addBlockedBy=["1"]     # API depends on database
TaskUpdate: id=3, addBlockedBy=["1","2"] # Tests depend on both

Rendered view:
#1. [>] Set up database          (in_progress)
#2. [ ] Write API endpoints      blocked by: #1
#3. [ ] Write tests              blocked by: #1, #2

When #1 completes -> _clear_dependency("1"):
#1. [x] Set up database          (completed)
#2. [ ] Write API endpoints      (now executable)
#3. [ ] Write tests              blocked by: #2
```

## File-Based Persistence

```python
def _task_path(self, task_id):
    return self.tasks_dir / f"{self._sanitize_id(task_id)}.json"

def _save_task(self, task):
    path = self._task_path(task.id)
    path.write_text(json.dumps(asdict(task), indent=2))
```

Task IDs are sanitized for filenames: non-alphanumeric characters (except `_` and `-`) are replaced with `-`. For example, task ID `"1"` becomes `1.json`.

Why files instead of a database:
- One file per task = fine-grained locking
- Subagents may run in separate processes
- JSON files are human-readable, easy to debug
- Task list ID resolved from `CLAUDE_CODE_TASK_LIST_ID` env > `CLAUDE_TEAM_NAME` env > `"default"` fallback

## Working with Compression (v5)

Tasks persist on disk, unaffected by compression:

```sh
Before compact: [100 turns of conversation] + [5 tasks on disk]
After compact:  [summary + recent 5 turns]  + [5 tasks on disk]  <- tasks intact
```

TodoWrite couldn't do this -- its tasks lived only in message history, gone after compression.

## The Deeper Insight

> **From personal notes to team kanban.**

TodoWrite is a sticky note -- one person uses it, then discards it. Tasks is a project board -- multi-party collaboration, state transitions, dependency tracking.

When agents evolve from individual to collective, task management must evolve from "checklist" to "system."

---

**A checklist keeps one agent organized. A task system keeps a team in order.**

[<-- v5](./v5-context-compression.md) | [Back to README](../README.md) | [v7 -->](./v7-background-tasks.md)
