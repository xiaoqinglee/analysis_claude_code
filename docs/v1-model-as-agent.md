# v1: The Model as Agent

**Core insight: Four tools cover 90% of coding tasks.**

v0 proves bash is enough for everything. But "enough" is not "ergonomic." Reading a file through `cat` and editing through `sed` works, but dedicated tools give the model structured input/output and safety guarantees.

## The Four-Tool Agent Loop

```sh
User input
    |
    v
+------------------+
| messages.create( |<-----------+
|   model, system, |            |
|   messages,      |            |
|   tools=4,       |            |
|   max_tokens=8K  |            |
| )                |            |
+--------+---------+            |
         |                      |
         v                      |
  stop_reason == "tool_use"?    |
         |                      |
    no --+-- yes                |
    |         |                 |
    v         v                 |
  return   for tc in calls:     |
  msgs       execute_tool(tc)   |
             collect results ---+
```

The loop is identical to v0. The difference is what happens inside `execute_tool`:

```python
def execute_tool(name, args):
    if name == "bash":      return run_bash(args["command"])
    if name == "read_file": return run_read(args["path"], args.get("limit"))
    if name == "write_file": return run_write(args["path"], args["content"])
    if name == "edit_file":  return run_edit(args["path"], args["old_text"], args["new_text"])
```

## The Four Tools

Production name mapping: bash->Bash, read_file->Read, write_file->Write, edit_file->Edit.

| Tool | Purpose | Key feature |
|------|---------|-------------|
| bash | Run any command | timeout=120s, dangerous command blocking |
| read_file | Read file contents | Optional line limit, output truncation |
| write_file | Create/overwrite files | Auto-creates parent directories |
| edit_file | Surgical text replacement | Exact string match, first occurrence only |

## Workspace Security

```python
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path
```

All file operations go through `safe_path()`, which resolves the path and checks it stays within the workspace. This prevents `../../../etc/passwd` attacks.

Bash also blocks dangerous patterns:

```python
dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
if any(d in command for d in dangerous):
    return "Error: Dangerous command blocked"
```

## edit_file: Exact String Matching

```python
def run_edit(path, old_text, new_text):
    content = safe_path(path).read_text()
    if old_text not in content:
        return f"Error: Text not found in {path}"
    new_content = content.replace(old_text, new_text, 1)  # First occurrence only
    safe_path(path).write_text(new_content)
```

The `replace(..., 1)` is deliberate: replacing only the first occurrence prevents accidental mass changes when the matched text appears multiple times.

## System Prompt

```python
SYSTEM = f"""You are a coding agent at {WORKDIR}.

Loop: think briefly -> use tools -> report results.

Rules:
- Prefer tools over prose. Act, don't just explain.
- Never invent file paths. Use bash ls/find first if unsure.
- Make minimal changes. Don't over-engineer.
- After finishing, summarize what changed."""
```

The system prompt teaches the agent its behavior pattern. The working directory is injected so the model knows where it is.

## v0 vs v1

| Aspect | v0 (bash only) | v1 (4 tools) |
|--------|---------------|-------------|
| File reading | cat, head, tail | read_file with line limit |
| File writing | echo, cat << EOF | write_file with auto-mkdir |
| File editing | sed -i | edit_file with exact match |
| Security | None | safe_path + dangerous command blocking |
| Timeout | 120s | 120s |

## The Deeper Insight

> **The model is the decision-maker. Code just provides tools and runs the loop.**

The model decides which tools to call, in what order, when to stop. Four tools give it structured access to the filesystem and shell. Everything else -- planning, subagents, compression -- is built on top of this foundation.

---

**Four tools. One loop. A complete coding agent.**

[<-- v0](./v0-bash-is-all-you-need.md) | [Back to README](../README.md) | [v2 -->](./v2-structured-planning.md)
