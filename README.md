# Learn Claude Code - Bash is all you & agent need

<p align="center">
  <img src="./assets/cover.webp" alt="Learn Claude Code" width="800">
</p>

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/shareAI-lab/learn-claude-code/actions/workflows/test.yml/badge.svg)](https://github.com/shareAI-lab/learn-claude-code/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)

> **Disclaimer**: This is an independent educational project by [shareAI Lab](https://github.com/shareAI-lab). It is not affiliated with, endorsed by, or sponsored by Anthropic. "Claude Code" is a trademark of Anthropic.

**Learn how modern AI agents work by building one from scratch.**

[Chinese / 中文](./README_zh.md) | [Japanese / 日本語](./README_ja.md)

---

## Why This Repository?

We created this repository out of admiration for Claude Code - **what we believe to be the most capable AI coding agent in the world**. Initially, we attempted to reverse-engineer its design through behavioral observation and speculation. The analysis we published was riddled with inaccuracies, unfounded guesses, and technical errors. We deeply apologize to the Claude Code team and anyone who was misled by that content.

Over the past six months, through building and iterating on real agent systems, our understanding of **"what makes a true AI agent"** has been fundamentally reshaped. We'd like to share these insights with you. All previous speculative content has been removed and replaced with original educational material.

---

> Works with **[Kode CLI](https://github.com/shareAI-lab/Kode)**, **Claude Code**, **Cursor**, and any agent supporting the [Agent Skills Spec](https://agentskills.io/specification).

<img height="400" alt="demo" src="https://github.com/user-attachments/assets/0e1e31f8-064f-4908-92ce-121e2eb8d453" />

## What You'll Learn

After completing this tutorial, you will understand:

- **The Agent Loop** - The surprisingly simple pattern behind all AI coding agents
- **Tool Design** - How to give AI models the ability to interact with the real world
- **Explicit Planning** - Using constraints to make AI behavior predictable
- **Context Management** - Keeping agent memory clean through subagent isolation
- **Knowledge Injection** - Loading domain expertise on-demand without retraining
- **Context Compression** - How agents work beyond their context window limits
- **Task Systems** - From personal notes to team project boards
- **Parallel Execution** - Background tasks and notification-driven workflows
- **Team Messaging** - Persistent teammates communicating through inboxes
- **Autonomous Teams** - Self-organizing agents that find and claim their own work

## Learning Path

```
Start Here
    |
    v
[v0: Bash Agent] ----------> "One tool is enough"
    |                         16-196 lines
    v
[v1: Basic Agent] ----------> "The complete agent pattern"
    |                          4 tools, ~417 lines
    v
[v2: Todo Agent] -----------> "Make plans explicit"
    |                          +TodoManager, ~531 lines
    v
[v3: Subagent] -------------> "Divide and conquer"
    |                          +Task tool, ~623 lines
    v
[v4: Skills Agent] ----------> "Domain expertise on-demand"
    |                           +Skill tool, ~783 lines
    v
[v5: Compression Agent] ----> "Never forget, work forever"
    |                          +ContextManager, ~896 lines
    v
[v6: Tasks Agent] ----------> "From sticky notes to kanban"
    |                          +TaskManager, ~1075 lines
    v
[v7: Background Agent] -----> "Don't wait, keep working"
    |                          +BackgroundManager, ~1142 lines
    v
[v8a: Team Foundation] --> "Creating and managing teammates"
    |                       +TeammateManager, ~1395 lines
    v
[v8b: Messaging] --------> "Teammates that communicate"
    |                       +SendMessage/Inbox, ~1557 lines
    v
[v8c: Coordination] -----> "Shared tasks and shutdown protocol"
    |                       +SharedBoard/Protocol, ~1612 lines
    v
[v9: Autonomous Agent] -----> "A self-organizing team"
                               +Idle cycle, ~1683 lines
```

**Recommended approach:**
1. Read and run v0 first - understand the core loop
2. Compare v0 and v1 - see how tools evolve
3. Study v2 for planning patterns
4. Explore v3 for complex task decomposition
5. Master v4 for building extensible agents
6. Study v5 for context management and compression
7. Explore v6 for persistent task tracking
8. Understand v7 for parallel background execution
9. Study v8a/v8b/v8c for team lifecycle and messaging
      a. v8a - TeammateManager (creation, deletion, config, tool scoping)
      b. v8b - Message protocol (5 types, JSONL inbox, inbox routing)
      c. v8c - Shared task board, shutdown protocol, plan approval
      d. Trace a full lifecycle across v8a -> v8b -> v8c
10. Master v9 for autonomous multi-agent collaboration

**Note:** v8 is split into three progressive sub-versions (v8a -> v8b -> v8c), each adding one concept. This makes the jump from v7 more gradual.

## Learning Progression

```
v0(196) -> v1(417) -> v2(531) -> v3(623) -> v4(783)
   |          |          |          |          |
 Bash      4 Tools    Planning   Subagent   Skills

-> v5(896) -> v6(1075) -> v7(1142) -> v8a(1395) -> v8b(1557) -> v8c(1612) -> v9(1683)
     |           |            |            |            |            |            |
 Compress     Tasks      Background   Foundation   Messaging   Coordination  Autonomous
```

## Quick Start

```bash
# Clone the repository
git clone https://github.com/shareAI-lab/learn-claude-code
cd learn-claude-code

# Install dependencies
pip install -r requirements.txt

# Configure API key
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# Run any version
python v0_bash_agent.py         # Minimal (start here!)
python v1_basic_agent.py        # Core agent loop
python v2_todo_agent.py         # + Todo planning
python v3_subagent.py           # + Subagents
python v4_skills_agent.py       # + Skills
python v5_compression_agent.py  # + Context compression
python v6_tasks_agent.py        # + Task system
python v7_background_agent.py   # + Background tasks
python v8a_team_foundation.py  # + Team foundation
python v8b_messaging.py        # + Team messaging
python v8c_coordination.py     # + Team coordination
python v9_autonomous_agent.py  # + Autonomous teams
```

## Running Tests

```bash
# Run full test suite
python tests/run_all.py

# Run unit tests only
python tests/test_unit.py

# Run tests for a specific version
python -m pytest tests/test_v8a.py tests/test_v8b.py tests/test_v8c.py -v
```

## The Core Pattern

Every coding agent is just this loop:

```python
while True:
    response = model(messages, tools)
    if response.stop_reason != "tool_use":
        return response.text
    results = execute(response.tool_calls)
    messages.append(results)
```

That's it. The model calls tools until done. Everything else is refinement.

## Version Comparison

| Version | Lines | Tools | Core Addition | Key Insight |
|---------|-------|-------|---------------|-------------|
| [v0](./v0_bash_agent.py) | ~196 | bash | Recursive subagents | One tool is enough |
| [v1](./v1_basic_agent.py) | ~417 | bash, read, write, edit | Core loop | Model as Agent |
| [v2](./v2_todo_agent.py) | ~531 | +TodoWrite | Explicit planning | Constraints enable complexity |
| [v3](./v3_subagent.py) | ~623 | +Task | Context isolation | Clean context = better results |
| [v4](./v4_skills_agent.py) | ~783 | +Skill | Knowledge loading | Expertise without retraining |
| [v5](./v5_compression_agent.py) | ~896 | +ContextManager | 3-layer compression | Forgetting enables infinite work |
| [v6](./v6_tasks_agent.py) | ~1075 | +TaskCreate/Get/Update/List | Persistent tasks | Sticky notes to kanban |
| [v7](./v7_background_agent.py) | ~1142 | +TaskOutput/TaskStop | Background execution | Serial to parallel |
| [v8a](./v8a_team_foundation.py) | ~1395 | +TeamCreate/TeamDelete | Team foundation | Building the team structure |
| [v8b](./v8b_messaging.py) | ~1557 | +SendMessage/Inbox | Team messaging | Communication channels |
| [v8c](./v8c_coordination.py) | ~1612 | +SharedBoard/Protocol | Team coordination | Command to collaboration |
| [v9](./v9_autonomous_agent.py) | ~1683 | +Idle cycle/auto-claim | Autonomous teams | Collaboration to self-organization |

## Sub-Mechanism Guide

Each version introduces one core class, but the real learning is in the sub-mechanisms. This map helps you find specific concepts:

| Sub-Mechanism | Version | Key Code | What to Look For |
|---------------|---------|----------|------------------|
| **Agent loop** | v0-v1 | `agent_loop()` | The `while tool_use` loop pattern |
| **Tool dispatch** | v1 | `process_tool_call()` | How tool_use blocks map to functions |
| **Explicit planning** | v2 | `TodoManager` | Single `in_progress` constraint, system reminders |
| **Context isolation** | v3 | `run_subagent()` | Fresh message list per subagent |
| **Tool filtering** | v3 | `AGENT_TYPES` | Explore agents get read-only tools |
| **Skill injection** | v4 | `SkillLoader` | Content prepended to system prompt |
| **Microcompact** | v5 | `ContextManager.microcompact()` | Old tool outputs replaced with placeholders |
| **Auto-compact** | v5 | `ContextManager.auto_compact()` | 85.3% threshold (formula-based) triggers API summarization |
| **Large output handling** | v5 | `ContextManager.handle_large_output()` | >40K tokens saved to disk, preview returned |
| **Transcript persistence** | v5 | `ContextManager.save_transcript()` | Full history appended to `.jsonl` |
| **Task CRUD** | v6 | `TaskManager` | create/get/update/list with JSON persistence |
| **Dependency graph** | v6 | `addBlocks/addBlockedBy` | Completion auto-unblocks dependents |
| **Background execution** | v7 | `BackgroundManager.run_in_background()` | Thread-based, immediate task_id return |
| **ID prefix convention** | v7 | `_PREFIXES` | `b`=bash, `a`=agent (v8 adds `t`=teammate) |
| **Notification bus** | v7 | `drain_notifications()` | Queue drained before each API call |
| **Notification injection** | v7 | attachment-based notification | Injected into last user message |
| **Teammate lifecycle** | v8a | `_teammate_loop()` | Work -> check inbox -> exit pattern |
| **Tool scoping** | v8a | `TEAMMATE_TOOLS` | Teammates get 9 tools (no TeamCreate/Delete/Task/Skill) |
| **File-based inbox** | v8b | `send_message()/check_inbox()` | JSONL format, per-teammate files |
| **Message protocol** | v8b | `MESSAGE_TYPES` | 5 types: message, broadcast, shutdown_req/resp, plan_approval |
| **Shutdown protocol** | v8c | `SharedBoard/Protocol` | Graceful shutdown and plan approval |
| **Idle cycle** | v9 | `_teammate_loop()` | active -> idle -> poll inbox -> wake -> active |
| **Task claiming** | v9 | `_teammate_loop()` | Idle teammates auto-claim unclaimed tasks |
| **Identity preservation** | v9 | `auto_compact` + identity | Teammate name/role re-injected after compression |

## File Structure

```
learn-claude-code/
|-- v0_bash_agent.py          # ~196 lines: 1 tool, recursive subagents
|-- v0_bash_agent_mini.py     # ~16 lines: extreme compression
|-- v1_basic_agent.py         # ~417 lines: 4 tools, core loop
|-- v2_todo_agent.py          # ~531 lines: + TodoManager
|-- v3_subagent.py            # ~623 lines: + Task tool, agent registry
|-- v4_skills_agent.py        # ~783 lines: + Skill tool, SkillLoader
|-- v5_compression_agent.py   # ~896 lines: + ContextManager, 3-layer compression
|-- v6_tasks_agent.py         # ~1075 lines: + TaskManager, CRUD with dependencies
|-- v7_background_agent.py    # ~1142 lines: + BackgroundManager, parallel execution
|-- v8a_team_foundation.py  # ~1395 lines: + TeammateManager, team lifecycle
|-- v8b_messaging.py        # ~1557 lines: + SendMessage, inbox, message protocol
|-- v8c_coordination.py     # ~1612 lines: + Shared task board, shutdown protocol
|-- v9_autonomous_agent.py    # ~1683 lines: + Idle cycle, auto-claim, identity preservation
|-- skills/                   # Example skills (pdf, code-review, mcp-builder, agent-builder)
|-- docs/                     # Technical documentation (EN + ZH + JA)
|-- articles/                 # Blog-style articles (ZH)
+-- tests/                    # Unit, feature, and integration tests
```

## Documentation

### Technical Tutorials (docs/)

- [v0: Bash is All You Need](./docs/v0-bash-is-all-you-need.md)
- [v1: Model as Agent](./docs/v1-model-as-agent.md)
- [v2: Structured Planning](./docs/v2-structured-planning.md)
- [v3: Subagent Mechanism](./docs/v3-subagent-mechanism.md)
- [v4: Skills Mechanism](./docs/v4-skills-mechanism.md)
- [v5: Context Compression](./docs/v5-context-compression.md)
- [v6: Tasks System](./docs/v6-tasks-system.md)
- [v7: Background Tasks](./docs/v7-background-tasks.md)
- [v8: Team Messaging](./docs/v8-team-messaging.md)
- [v9: Autonomous Teams](./docs/v9-autonomous-teams.md)

### Articles

See [articles/](./articles/) for blog-style explanations.

## Using the Skills System

### Example Skills Included

| Skill | Purpose |
|-------|---------|
| [agent-builder](./skills/agent-builder/) | Meta-skill: how to build agents |
| [code-review](./skills/code-review/) | Systematic code review methodology |
| [pdf](./skills/pdf/) | PDF manipulation patterns |
| [mcp-builder](./skills/mcp-builder/) | MCP server development |

### Scaffold a New Agent

```bash
# Use the agent-builder skill to create a new project
python skills/agent-builder/scripts/init_agent.py my-agent

# Specify complexity level
python skills/agent-builder/scripts/init_agent.py my-agent --level 0  # Minimal
python skills/agent-builder/scripts/init_agent.py my-agent --level 1  # 4 tools
```

### Install Skills for Production

```bash
# Kode CLI (recommended)
kode plugins install https://github.com/shareAI-lab/shareAI-skills

# Claude Code
claude plugins install https://github.com/shareAI-lab/shareAI-skills
```

## Configuration

```bash
# .env file options
ANTHROPIC_API_KEY=sk-ant-xxx      # Required: Your API key
ANTHROPIC_BASE_URL=https://...    # Optional: For API proxies
MODEL_ID=claude-sonnet-4-5-20250929  # Optional: Model selection
```

## Related Projects

| Repository | Description |
|------------|-------------|
| [Kode](https://github.com/shareAI-lab/Kode) | Production-ready open source agent CLI |
| [shareAI-skills](https://github.com/shareAI-lab/shareAI-skills) | Production skills collection |
| [Agent Skills Spec](https://agentskills.io/specification) | Official specification |

## Philosophy

> **The model is 80%. Code is 20%.**

Modern agents like Kode and Claude Code work not because of clever engineering, but because the model is trained to be an agent. Our job is to give it tools and stay out of the way.

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

- Add new example skills in `skills/`
- Improve documentation in `docs/`
- Report bugs or suggest features via [Issues](https://github.com/shareAI-lab/learn-claude-code/issues)

## License

MIT

---

**Model as Agent. That's the whole secret.**

[@baicai003](https://x.com/baicai003) | [shareAI Lab](https://github.com/shareAI-lab)
