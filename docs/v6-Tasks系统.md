# v6: Tasks 系统

**核心洞察：从个人便利贴到团队看板。**

v2 引入的 TodoWrite 解决了"模型忘记计划"的问题。但现在我们有了压缩（v5）和子代理（v3），TodoWrite 的局限暴露了。

## 问题

```
TodoWrite 的问题：
  1. 写入只有覆盖模式（每次发送完整列表）
  2. 没有持久化（压缩后 todo 丢失）
  3. 没有所有者（谁在做这个任务？）
  4. 没有依赖关系（A 必须在 B 之前完成）
  5. 没有并发安全（两个代理同时写 = 数据丢失）
```

v5 的压缩会清除内存中的 todo。子代理之间无法共享任务。Tasks 系统从根本上重新设计了任务管理。

## TodoWrite vs Tasks

| 特性 | TodoWrite (v2) | Tasks (v6) |
|------|---------------|------------|
| 操作方式 | 覆盖写入 | CRUD（创建/读取/更新/删除） |
| 持久化 | 仅内存（压缩后丢失） | 磁盘文件（压缩后存活） |
| 并发 | 不安全 | 文件锁 |
| 依赖 | 无 | blocks / blockedBy |
| 所有者 | 无 | agent name |
| 多代理 | 不支持 | 原生支持 |

## 数据模型

```python
@dataclass
class Task:
    id: str              # 自增 ID（高水位线）
    subject: str         # 祈使句标题: "Fix auth bug"
    description: str     # 详细描述
    status: str = "pending"  # pending | in_progress | completed
    active_form: str = ""    # 进行时态: "Fixing auth bug"
    owner: str = ""          # 负责的代理
    blocks: list = []        # 被此任务阻塞的任务
    blocked_by: list = []    # 阻塞此任务的前置任务
    metadata: dict = {}      # 任意键值对
```

为什么每个字段都需要：

| 字段 | 原因 |
|------|------|
| `id` | CRUD 需要唯一标识 |
| `owner` | 多代理时标识谁在做 |
| `blocks/blockedBy` | 任务编排的依赖图 |
| `description` | 另一个代理也能理解任务 |
| `metadata` | 可扩展的键值数据 |

## 任务状态机

```
+--------+     update(status)     +-------------+     update(status)     +-----------+
| pending| ------------------->   | in_progress | ------------------->   | completed |
+--------+                        +-------------+                        +-----------+
    ^                                    |
    |          update(status)            |
    +------------------------------------+
                  (重新打开)

  任何状态 ---> deleted (文件从磁盘物理删除)
```

当任务转为 `completed` 时，依赖它的任务的 `blocked_by` 列表会自动更新。

## 高水位线 ID 分配

任务 ID 通过高水位线文件（`.highwatermark`）分配，而不是扫描现有任务文件：

```python
HIGHWATERMARK_FILE = ".highwatermark"

def _next_id(self):
    """获取下一个任务 ID 并持久化高水位线"""
    with self._lock:
        self._highwatermark += 1
        (self.tasks_dir / HIGHWATERMARK_FILE).write_text(str(self._highwatermark))
        return str(self._highwatermark)
```

这防止了任务被删除后 ID 被重用。启动时从文件加载高水位线，如果文件不存在则回退到扫描现有任务文件。

## 状态变更时自动分配 Owner

当任务转入 `in_progress` 且没有 owner 时，代理自动将自己设为 owner：

```python
if kwargs.get("status") == "in_progress" and not task.owner:
    task.owner = kwargs.get("owner", os.getenv("CLAUDE_AGENT_NAME", "agent"))
```

这省去了模型每次开始任务时显式设置 `owner` 的步骤。

## 四个工具

```python
# TaskCreate: 创建任务
task_create("Fix auth bug", description="...", active_form="Fixing auth bug")
# -> {"id": "1", "subject": "Fix auth bug"}

# TaskGet: 读取详情
task_get("1")
# -> {id, subject, description, status, blocks, blockedBy}

# TaskUpdate: 更新状态、依赖、所有者
task_update("1", status="in_progress")  # 自动分配 owner
task_update("2", addBlockedBy=["1"])    # 2 依赖 1

# TaskList: 列出所有任务
task_list()
# -> [{id, subject, status, owner, blockedBy}, ...]
```

## 依赖图

```
TaskCreate: "Set up database"       -> #1
TaskCreate: "Write API endpoints"   -> #2
TaskCreate: "Write tests"           -> #3

TaskUpdate: id=2, addBlockedBy=["1"]     # API 依赖数据库
TaskUpdate: id=3, addBlockedBy=["1","2"] # 测试依赖两者
```

渲染效果：

```
#1. [>] Set up database          (in_progress)
#2. [ ] Write API endpoints      blocked by: #1
#3. [ ] Write tests              blocked by: #1, #2
```

当 #1 完成后，#2 的 blockedBy 自动清除，变为可执行。

## 持久化

```python
def _task_path(self, task_id):
    return self.tasks_dir / f"{self._sanitize_id(task_id)}.json"

def save_task(task):
    """线程锁保证并发安全（生产环境使用文件锁 proper-lockfile）"""
    path = self._task_path(task.id)
    path.write_text(json.dumps(asdict(task), indent=2))
```

任务 ID 经过清洗（非字母数字字符替换为 `-`）作为文件名。例如 ID `"1"` 变为 `1.json`。

为什么用文件而不是数据库？
- 每个任务一个文件 = 细粒度锁
- 子代理可能在不同进程中
- JSON 文件人类可读，方便调试
- 任务列表 ID 解析顺序：`CLAUDE_CODE_TASK_LIST_ID` 环境变量 > `CLAUDE_TEAM_NAME` 环境变量 > `"default"` 回退

## 与压缩的协作 (v5)

Tasks 持久化在磁盘上，压缩时不会丢失：

```
压缩前:  [100 轮对话] + [5 个任务在磁盘上]
压缩后:  [摘要 + 最近 5 轮] + [5 个任务在磁盘上]  <- 任务完整保留
```

这是 TodoWrite 无法做到的——TodoWrite 的任务只在消息历史中，压缩后就没了。

## Feature Gate

在我们的教学代码中，v6 用 Tasks 系统完全替代了 TodoWrite。两个系统在概念上互斥：

```python
# v2 使用 TodoWrite（内存中，只能全量覆盖）
# v6 使用 TaskCreate/Get/Update/List（磁盘持久化，CRUD 操作）

# 在实现中，v6 直接包含 Tasks 工具并移除 TodoWrite
ALL_TOOLS = BASE_TOOLS + [TASK_CREATE_TOOL, TASK_GET_TOOL,
                          TASK_UPDATE_TOOL, TASK_LIST_TOOL]
```

关键区别：TodoWrite 的数据只存在于消息历史中（压缩后丢失），而 Tasks 的数据存在于磁盘上（压缩后依然存在）。

## 更深的洞察

> **从个人笔记到团队看板。**

TodoWrite 像是便利贴——一个人用，用完就扔。Tasks 像是项目看板——多人协作，有状态流转，有依赖追踪。

这是**协作范式的转变**：
- TodoWrite: 模型的自我约束工具（v2 的哲学：约束赋能）
- Tasks: 多代理的协调协议（v6 的哲学：协作赋能）

当 Agent 从单体变成群体，任务管理必须从"清单"进化为"系统"。

---

**清单让一个 Agent 有条理，任务系统让一群 Agent 有秩序。**

[← v5](./v5-上下文压缩.md) | [返回 README](../README_zh.md) | [v7 →](./v7-后台任务与通知Bus.md)
