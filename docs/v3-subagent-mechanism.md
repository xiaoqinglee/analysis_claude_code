# v3: Subagent Mechanism

**Core insight: Process isolation = context isolation.**

v2 adds planning. But for large tasks like "explore the codebase then refactor auth," a single agent hits a wall: its context fills with exploration details, leaving little room for actual work. This is **context pollution**.

## Subagent Lifecycle

```sh
Main Agent (history=[..., 50 turns])
    |
    | Task(subagent_type="Explore", prompt="Find auth files")
    v
+---------------------------------------------+
| Subagent                                    |
|                                             |
|  sub_messages = [{"role":"user", prompt}]   <-- fresh history
|  sub_tools = [bash, read_file]              <-- filtered (no Task)
|  sub_system = "You are an explore agent..." <-- specialized prompt
|                                             |
|  while True:                                |
|    response = model(sub_messages, sub_tools) |
|    if stop_reason != "tool_use": break      |
|    execute tools, append results            |
|                                             |
|  return final_text                          <-- only summary
+---------------------------------------------+
    |
    v
Main Agent receives: "Auth in src/auth/login.py, src/auth/jwt.py..."
(Main context stays clean -- never saw the 10 files subagent read)
```

The parent agent sees only the final summary. All intermediate tool calls, file contents, and exploration details stay in the subagent's isolated context.

## Agent Type Registry

```python
AGENT_TYPES = {
    "Explore": {
        "tools": ["bash", "read_file"],          # Read-only
        "prompt": "Search and analyze, but never modify files.",
    },
    "general-purpose": {
        "tools": "*",                             # All base tools
        "prompt": "Implement the requested changes efficiently.",
    },
    "Plan": {
        "tools": ["bash", "read_file"],          # Read-only
        "prompt": "Analyze and output a numbered plan. Do NOT make changes.",
    },
}
```

| Type | Tools | Purpose |
|------|-------|---------|
| Explore | bash, read_file | Read-only exploration |
| general-purpose | all base tools | Full implementation access |
| Plan | bash, read_file | Design without modifying |

## Tool Filtering

```python
def get_tools_for_agent(agent_type):
    allowed = AGENT_TYPES[agent_type]["tools"]
    if allowed == "*":
        return BASE_TOOLS           # All base tools, but NOT Task
    return [t for t in BASE_TOOLS if t["name"] in allowed]
```

Subagents never get the `Task` tool. This prevents infinite recursion (a subagent spawning another subagent spawning another...). In v0, this was handled by process boundaries; in v3, it is handled by tool filtering.

## The Task Tool

```python
TASK_TOOL = {
    "name": "Task",
    "description": "Spawn a subagent for a focused subtask.",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {"type": "string"},    # Short name for display
            "prompt": {"type": "string"},          # Detailed instructions
            "subagent_type": {"type": "string", "enum": ["Explore", "general-purpose", "Plan"]},
        },
        "required": ["description", "prompt", "subagent_type"],
    },
}

ALL_TOOLS = BASE_TOOLS + [TASK_TOOL]   # Main agent gets Task
# Subagents get only filtered BASE_TOOLS (no Task)
```

## Progress Display

While a subagent runs, progress is shown in-place:

```sh
  [Explore] find auth files ... 5 tools, 3.2s
  [Explore] find auth files - done (8 tools, 5.1s)
```

This gives visibility without polluting the main conversation's context.

## Typical Flow

```sh
User: "Refactor auth to use JWT"

Main Agent:
  1. Task(Explore): "Find all auth-related files"
     -> Subagent reads 10 files
     -> Returns: "Auth in src/auth/login.py..."

  2. Task(Plan): "Design JWT migration"
     -> Subagent analyzes structure
     -> Returns: "1. Add jwt lib 2. Create utils..."

  3. Task(general-purpose): "Implement JWT tokens"
     -> Subagent writes code
     -> Returns: "Created jwt_utils.py, updated login.py"

  4. Summarize changes to user
```

Three subagents, each with clean context, each returning only a summary.

## v0 Recursion vs v3 Subagents

| Aspect | v0 (self-recursion) | v3 (Task tool) |
|--------|--------------------|--------------  |
| Isolation | Process boundary | Message history |
| Tools | Same (bash only) | Filtered per type |
| Communication | stdout capture | Return value |
| Spawning | `python v0_bash_agent.py "task"` | `Task(subagent_type, prompt)` |
| Nesting | Unlimited | One level (no Task tool in subagents) |

## The Deeper Insight

> **Divide context, not just tasks.**

The real value of subagents is not parallelism (v3 subagents are synchronous). It is **context management**. By isolating exploration from implementation, each phase has full context window available. The parent stays clean, focused on orchestration.

---

**Clean context enables clean thinking.**

[<-- v2](./v2-structured-planning.md) | [Back to README](../README.md) | [v4 -->](./v4-skills-mechanism.md)
