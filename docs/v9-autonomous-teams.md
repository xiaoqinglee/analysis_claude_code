# v9: Autonomous Teams

**Core insight: A truly capable team does not wait for orders -- it finds its own work.**

v8 gave us teammates: persistent agents that communicate through inboxes and share a task board. But v8 teammates are reactive -- they execute their initial prompt, check for messages, and shut down when there is nothing left. They do not autonomously pick up new work.

v9 adds the missing piece: **teammate autonomy**. Teammates go idle when their work is done, poll for new messages and unclaimed tasks, and wake up when they find something to do.

## v8 vs v9 Teammate Comparison

```sh
v8 Teammate (one-shot):
  spawn -> work (tool loop) -> check inbox -> nothing? -> shutdown

  +-------+     +------+     +-------+     +---------+
  | spawn | --> | work | --> | check | --> | shutdown|
  +-------+     +------+     | inbox |     +---------+
                              +---+---+
                                  |
                              msg found? --> back to work
                              (one chance)

v9 Teammate (persistent with idle cycle):
  spawn -> work (tool loop) -> idle (poll 1s x 60) -> wake or timeout

  +-------+     +------+          +------+
  | spawn | --> | WORK | -------> | IDLE | -------> timeout? -> shutdown
  +-------+     +--+---+          +--+---+
                   ^                 |
                   |     msg/task    |    poll every 1s
                   +----- found -----+    for 60 seconds
                                     |
                                     +--- check inbox
                                     |    - shutdown_request -> exit
                                     |    - message -> resume WORK
                                     |
                                     +--- scan unclaimed tasks
                                          - found -> claim -> resume WORK
```

## What v9 Adds to v8

| Feature | v8 (Team Messaging) | v9 (Autonomous Teams) |
|---------|---------------------|----------------------|
| Teammate loop | Work then exit | Work -> idle -> wake -> work |
| Task claiming | None (lead assigns) | Auto-claim unclaimed tasks |
| Idle cycle | None | 1s polling, 60s timeout |
| Identity preservation | None | Re-inject after compression |
| Plan approval | Stub | Full protocol support |

## Autonomous Teammate Lifecycle

```sh
+-------+
| spawn |
+---+---+
    |
    v
+-------+    tool_use     +---------+
| WORK  | <------------- | API call |
| phase |                 +---------+
+---+---+
    |
    | stop_reason != tool_use
    v
+--------+
| IDLE   |  <-- poll every IDLE_POLL_INTERVAL (1s)
| phase  |      for IDLE_TIMEOUT (60s)
+---+----+
    |
    +-------> check inbox
    |         - shutdown_request? -> exit
    |         - plan_approval?    -> handle approval
    |         - new message?      -> resume WORK
    |
    +-------> _scan_unclaimed_tasks()
    |         - found? -> _claim_task() -> resume WORK
    |
    +-------> IDLE_TIMEOUT expired with no new work?
              -> shutdown (graceful exit)
```

## Autonomy Constants

```python
IDLE_POLL_INTERVAL = 1     # seconds between idle polls (cli.js cZz=1000ms)
IDLE_TIMEOUT = 60          # seconds before giving up on new work

IDLE_REASONS = {
    "no_tool_use": "Model returned without tool calls",
    "awaiting_messages": "Polling inbox for new messages",
    "awaiting_tasks": "Scanning board for unclaimed tasks",
    "timeout": "Idle timeout expired with no new work",
}
```

## Production vs Teaching Simplification

| Aspect | Production cli.js | Our Teaching Version |
|--------|------------------|---------------------|
| Idle mechanism | Passive turn-level idle (agent waits for input injection) | Active polling loop (sleep 1s, check inbox/board) |
| Auto-claiming | Prompt-driven (model calls TaskList + TaskUpdate) | Code-driven (`_scan_unclaimed_tasks()` in idle loop) |
| Identity injection | Handled by system attachment pipeline | Explicit re-injection after `auto_compact` |

The teaching version uses active polling to make the idle/wake pattern explicit and observable. Production achieves the same effect through turn-level event injection.

## The Full Teammate Loop

```python
def _teammate_loop(self, teammate, initial_prompt):
    sub_system = f"You are teammate '{teammate.name}' in team '{teammate.team_name}'..."
    sub_messages = [{"role": "user", "content": initial_prompt}]

    while teammate.status != "shutdown":
        # === Active phase: normal agent loop ===
        teammate.status = "active"

        sub_messages = CTX.microcompact(sub_messages)
        if CTX.should_compact(sub_messages):
            sub_messages = CTX.auto_compact(sub_messages)
            # Re-inject identity after compression
            identity = f"\n\nRemember: You are teammate '{teammate.name}'."
            if sub_messages and sub_messages[0].get("role") == "user":
                sub_messages[0]["content"] += identity

        response = client.messages.create(
            model=MODEL, system=sub_system,
            messages=sub_messages, tools=TEAMMATE_TOOLS, max_tokens=8000,
        )

        if response.stop_reason == "tool_use":
            results = [execute(tc) for tc in tool_calls]
            sub_messages.append({"role": "assistant", "content": response.content})
            sub_messages.append({"role": "user", "content": results})
            continue

        # === Idle phase: wait for new messages or unclaimed tasks ===
        teammate.status = "idle"
        teammate.idle_reason = IDLE_REASONS["no_tool_use"]

        polls = IDLE_TIMEOUT // IDLE_POLL_INTERVAL
        for _ in range(polls):  # 60 checks x 1s = 60s
            if teammate.status == "shutdown":
                return

            teammate.idle_reason = IDLE_REASONS["awaiting_messages"]
            new_messages = self.check_inbox(teammate.name, teammate.team_name)
            if new_messages:
                if any(m.get("type") == "shutdown_request" for m in new_messages):
                    return
                sub_messages.append({"role": "user", "content": format(new_messages)})
                break

            teammate.idle_reason = IDLE_REASONS["awaiting_tasks"]
            unclaimed = [t for t in TASK_MGR.list_all()
                         if t.status == "pending" and not t.owner and not t.blocked_by]
            if unclaimed:
                TASK_MGR.update(unclaimed[0].id, status="in_progress", owner=teammate.name)
                sub_messages.append({
                    "role": "user",
                    "content": f"Task #{unclaimed[0].id}: {unclaimed[0].subject}\n{unclaimed[0].description}"
                })
                break

            time.sleep(IDLE_POLL_INTERVAL)
        else:
            # IDLE_TIMEOUT expired with no new work
            teammate.idle_reason = IDLE_REASONS["timeout"]
            return
```

## Auto-Claiming Tasks

Teammates autonomously claim work from the shared task board:

```python
unclaimed = [t for t in TASK_MGR.list_all()
             if t.status == "pending" and not t.owner and not t.blocked_by]
if unclaimed:
    task = unclaimed[0]
    TASK_MGR.update(task.id, status="in_progress", owner=teammate.name)
```

First-come-first-served by task ID. The thread lock in `TaskManager.update()` prevents race conditions when multiple teammates try to claim the same task.

In production, auto-claiming is prompt-driven: the model is instructed to call TaskList and TaskUpdate itself. Our code-level implementation makes the concept explicit for teaching purposes.

## Identity Preservation After Compression

When a teammate's context is compressed, the summary does not preserve who the teammate is. The loop re-injects identity:

```python
if CTX.should_compact(sub_messages):
    sub_messages = CTX.auto_compact(sub_messages)
    identity = f"\n\nRemember: You are teammate '{teammate.name}' in team '{teammate.team_name}'."
    sub_messages[0]["content"] += identity
```

Without this, a teammate could "forget" it is part of a team after auto-compact and behave like a standalone agent.

## Full Collaboration Flow

```sh
User: "Migrate the app from REST to GraphQL"

Team Lead:
  1. TeamCreate("rest-to-graphql")
  2. TaskCreate("Analyze REST endpoints")          -> #1
  3. TaskCreate("Design GraphQL schema")           -> #2, blockedBy=#1
  4. TaskCreate("Implement resolvers")             -> #3, blockedBy=#2
  5. TaskCreate("Update frontend")                 -> #4, blockedBy=#3

  6. Task(name="analyst", team_name=..., prompt="Analyze REST endpoints")
  7. Task(name="backend", team_name=..., prompt="Handle backend tasks")
  8. Task(name="frontend", team_name=..., prompt="Handle frontend migration")

analyst:   claims #1 -> done -> idle -> (no more tasks) -> stays idle
backend:   idle... <- #2 unblocked -> claims #2 -> done -> claims #3 -> done -> idle
frontend:  idle... <- #4 unblocked -> claims #4 -> done -> idle

Team Lead: all tasks done -> TeamDelete -> "Migration complete."
```

Four mechanisms working together:
- **Tasks (v6)** is the shared board -- everyone sees the same progress
- **Compression (v5)** lets each role work long -- no context limit
- **Message protocol (v8)** lets roles communicate freely
- **Autonomy (v9)** lets teammates self-organize -- no micromanagement

## v0 to v9: The Complete Story

```sh
v0: One agent, one tool
v1: One agent, multiple tools
v2: One agent, with a plan
v3: One agent, can dispatch workers
v4: One agent, with domain knowledge
v5: One agent, can forget and keep working
v6: Multiple agents, with a shared board
v7: Multiple agents, working in parallel
v8: Multiple agents, communicating (v8a foundation -> v8b messaging -> v8c coordination)
v9: Multiple agents, self-organizing
```

Each step solves the bottleneck exposed by the previous one.

## The Deeper Insight

> **A team that manages itself.**

v8 teammates are colleagues: they communicate, share a board, work in parallel. But they still wait for explicit instructions. v9 teammates are autonomous: they find unclaimed work, claim it, execute it, and return to idle.

```sh
v8 Teammate -> executes assigned work, communicates results  (junior)
v9 Teammate -> finds work, claims it, executes, stays ready  (senior)
Team Lead   -> breaks down work, reviews, coordinates         (manager)
```

The ultimate form of an agent system is not a smarter model, but **a group of models that can collaborate and self-organize**.

---

**One agent has limits. A team of autonomous agents has none.**

[<-- v8](./v8-team-messaging.md) | [Back to README](../README.md)
