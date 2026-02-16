# v2: Structured Planning

**Core insight: Structure constrains AND enables.**

v1 works for simple tasks. Ask it to "refactor auth, add tests, update docs" and watch: without explicit planning, the model jumps between tasks, forgets completed steps, loses focus. Plans exist only in the model's "head" -- invisible and fragile.

## The Problem: Context Fade

```sh
v1: "I'll do A, then B, then C"     (invisible plan)
    After 10 tool calls: "Wait, what was I doing?"

v2: [ ] Refactor auth module
    [>] Add unit tests              <- Currently working on this
    [ ] Update documentation

    Now both YOU and the MODEL can see the plan.
```

## TodoWrite State Machine

```sh
                  TodoWrite(status)
  +----------+  ----------------->  +--------------+  ----------------->  +-----------+
  | pending  |                      | in_progress  |                      | completed |
  |   [ ]    |                      |     [>]      |                      |    [x]    |
  +----------+                      +--------------+                      +-----------+

  Constraint: only ONE item can be in_progress at a time
  Constraint: maximum 20 items in the list
  Constraint: each item requires content, status, activeForm
```

The `activeForm` field is the present tense form shown when a task is active (e.g., content="Add tests", activeForm="Adding unit tests..."). This gives real-time visibility into what the agent is doing.

## TodoManager

Production uses TaskCreate/TaskUpdate (TodoWrite is legacy).

```python
class TodoManager:
    def update(self, items: list) -> str:
        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            active_form = str(item.get("activeForm", "")).strip()

            if not content:
                raise ValueError(f"Item {i}: content required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {i}: invalid status '{status}'")
            if not active_form:
                raise ValueError(f"Item {i}: activeForm required")
            if status == "in_progress":
                in_progress_count += 1

            validated.append({"content": content, "status": status, "activeForm": active_form})

        if len(validated) > 20:
            raise ValueError("Max 20 todos allowed")
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")

        self.items = validated
        return self.render()
```

The model sends a **complete new list** each time (not a diff). The manager validates it and returns a rendered view.

## Rendered Output

```sh
[x] Refactor auth module
[>] Add unit tests <- Adding unit tests...
[ ] Update documentation

(1/3 completed)
```

This rendered text is the tool result. The model sees it and can update the list based on its current state.

## Soft Prompts: Reminders

v2 uses two reminder mechanisms to encourage (not force) todo usage:

```python
# Shown at the start of conversation
INITIAL_REMINDER = "<reminder>Use TodoWrite for multi-step tasks.</reminder>"

# Shown if model hasn't updated todos in 10+ rounds
NAG_REMINDER = "<reminder>10+ turns without todo update. Please update todos.</reminder>"
```

The NAG_REMINDER is injected inside the agent loop when `rounds_without_todo > 10`:

```python
if used_todo:
    rounds_without_todo = 0
else:
    rounds_without_todo += 1

if rounds_without_todo > 10:
    results.insert(0, {"type": "text", "text": NAG_REMINDER})
```

## Key Constraints

| Rule | Why |
|------|-----|
| Max 20 items | Prevents infinite task lists |
| One in_progress | Forces focus on one thing at a time |
| Required fields | Ensures structured, usable output |
| Complete list replacement | Simpler than diff-based updates |

These constraints are not limitations -- they are scaffolding. The `max_tokens` constraint enables manageable responses. Tool schemas constrain but enable structured calls. Todo constraints constrain but enable complex task completion.

## The Deeper Insight

> **Good constraints are scaffolding, not walls.**

The pattern appears everywhere in agent design: constraints that seem limiting actually create structure that makes harder things possible. One in_progress at a time seems limiting, but it prevents the agent from thrashing between tasks.

---

**Plans in the model's head are invisible. Plans in a tool are actionable.**

[<-- v1](./v1-model-as-agent.md) | [Back to README](../README.md) | [v3 -->](./v3-subagent-mechanism.md)
