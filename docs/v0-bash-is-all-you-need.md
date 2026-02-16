# v0: Bash is All You Need

**Core insight: One tool + one loop = a complete agent.**

Strip away every feature of Claude Code, Cursor Agent, Codex CLI. What remains is a loop that lets the model call bash until done. Everything else -- file tools, planning, subagents -- is optimization on top of this core.

## The Agent Loop

```sh
User prompt
    |
    v
+-------------------+
| messages.create() |<---------+
| model + tools     |          |
+--------+----------+          |
         |                     |
         v                     |
  stop_reason == "tool_use"?   |
         |                     |
    no --+-- yes               |
    |         |                |
    v         v                |
  return   execute bash        |
  text     append result ------+
```

The model decides everything: which commands to run, in what order, when to stop. The code just provides the loop and the tool.

## One Tool Definition

```python
TOOL = [{
    "name": "bash",
    "description": """Execute shell command. Common patterns:
- Read: cat/head/tail, grep/find/rg/ls, wc -l
- Write: echo 'content' > file, sed -i 's/old/new/g' file
- Subagent: python v0_bash_agent.py 'task description'""",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"]
    }
}]
```

The description teaches the model common patterns. The last line is the key insight: calling itself via bash implements subagents without a Task tool.

## The Complete Agent

```python
def chat(prompt, history=None):
    if history is None:
        history = []
    history.append({"role": "user", "content": prompt})

    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM,
            messages=history, tools=TOOL, max_tokens=8000
        )
        # Preserve both text and tool_use blocks in assistant message
        history.append({"role": "assistant", "content": content})

        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if hasattr(b, "text"))

        results = []
        for block in response.content:
            if block.type == "tool_use":
                out = subprocess.run(
                    block.input["command"], shell=True,
                    capture_output=True, text=True, timeout=120, cwd=os.getcwd()
                )
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": (out.stdout + out.stderr)[:50000]
                })
        history.append({"role": "user", "content": results})
```

Key parameters: `timeout=120` seconds per command (production default, max 600s), output truncated to 50000 characters.

## Subagent via Self-Recursion

```sh
Main Agent (PID 100, history=[...])
  |
  +-- bash: python v0_bash_agent.py "analyze architecture"
       |
       Subagent (PID 200, history=[])   <-- fresh, isolated context
         |-- bash: find . -name "*.py"
         |-- bash: cat src/main.py
         +-- Returns summary via stdout
  |
  Main Agent captures stdout as tool result
```

Process isolation = context isolation. The child process has its own `history=[]`, so the parent's context stays clean. This is implemented through `__main__`:

```python
if len(sys.argv) > 1:
    print(chat(sys.argv[1]))   # Subagent mode
else:
    # Interactive REPL mode
```

## Why Bash is Enough

| You need    | Bash command                          |
|-------------|---------------------------------------|
| Read files  | cat, head, tail, grep                 |
| Write files | echo '...' > file, cat << 'EOF' > file|
| Search      | find, grep, rg, ls                    |
| Execute     | python, npm, make, any command        |
| Subagent    | python v0_bash_agent.py "task"         |

Unix philosophy says everything is a file, everything can be piped. Bash is the gateway to this world. One tool covers all of it.

## The Deeper Insight

> **The model IS the agent. Code just provides the loop.**

There is no scheduler, no planner, no state machine in the code. The model decides what to do, the loop executes it. The simplest possible agent is already surprisingly capable.

---

**Everything starts with a loop and a shell.**

[Back to README](../README.md) | [v1 -->](./v1-model-as-agent.md)
