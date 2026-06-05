# Daily Review Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建一个项目级 `daily-review` skill，可靠采集当前项目当天上下文，逐题检验技术理解与独立思考，并生成连续编号的复盘报告。

**Architecture:** Python 标准库脚本负责把 Codex JSONL、当前分支 Git 记录、工作区 diff 和历史复盘归一化为 JSON。`SKILL.md` 只负责依据证据组织面试、控制逐题追问、评分和写报告，避免把确定性数据处理交给模型临时拼接。

**Tech Stack:** Python 3 标准库、`unittest`、Git CLI、Codex skill Markdown、YAML

---

## File Structure

- `skills/daily-review/scripts/collect_context.py`: 采集并输出结构化复盘证据。
- `skills/daily-review/tests/test_collect_context.py`: 覆盖会话过滤、Git 数据和报告编号。
- `skills/daily-review/SKILL.md`: 定义逐题面试、评分和报告写入流程。
- `skills/daily-review/agents/openai.yaml`: Codex UI 元数据。

### Task 1: Context Collector Tests

**Files:**
- Create: `skills/daily-review/tests/test_collect_context.py`

- [ ] **Step 1: Write failing tests for conversation filtering**

使用临时 Git 仓库和临时 `CODEX_HOME` 创建三份 JSONL：当天当前项目、当天其他项目、前一天当前项目。断言只返回第一份中的 `user`、`assistant` 文本，并过滤系统提示和工具数据。

核心断言：

```python
self.assertEqual(
    result["conversations"][0]["messages"],
    [
        {"role": "user", "text": "为什么使用 SSE？"},
        {"role": "assistant", "text": "因为服务端需要持续推送。"},
    ],
)
```

- [ ] **Step 2: Write failing tests for Git evidence**

创建一个当天提交并留下未提交修改，断言：

```python
self.assertEqual(len(result["git"]["commits"]), 1)
self.assertIn("feat: add stream", result["git"]["commits"][0]["subject"])
self.assertIn("working tree change", result["git"]["working_tree_diff"])
```

- [ ] **Step 3: Write failing tests for review numbering**

创建 `daily-reviews/01-2026-06-03.md` 和 `02-2026-06-04.md`，断言新日期返回 `03-2026-06-05.md`；再创建该文件，断言同一天复用它。

- [ ] **Step 4: Run tests and verify RED**

Run:

```bash
python3 -m unittest skills/daily-review/tests/test_collect_context.py -v
```

Expected: FAIL because `collect_context.py` does not exist.

### Task 2: Context Collector Implementation

**Files:**
- Create: `skills/daily-review/scripts/collect_context.py`
- Test: `skills/daily-review/tests/test_collect_context.py`

- [ ] **Step 1: Implement project and date boundaries**

实现：

```python
def resolve_project_root(project_path: Path) -> Path: ...
def resolve_review_date(raw_date: str | None, timezone_name: str) -> date: ...
def is_within_project(candidate: Path, project_root: Path) -> bool: ...
```

默认时区为 `Asia/Shanghai`，允许 `--date YYYY-MM-DD` 仅用于测试和补做复盘。

- [ ] **Step 2: Implement Codex JSONL extraction**

遍历：

```text
$CODEX_HOME/sessions/YYYY/MM/DD/*.jsonl
$CODEX_HOME/archived_sessions/*.jsonl
```

以 `session_meta.payload.cwd` 或 `turn_context.payload.cwd` 判定项目，只读取目标日期内 `response_item.payload.type == "message"` 且角色为 `user`/`assistant` 的文本内容。过滤 AGENTS 注入、`environment_context`、系统/开发者消息和工具输出。

- [ ] **Step 3: Implement Git evidence collection**

仅查询当前分支：

```bash
git log <branch> --since=<day-start> --until=<next-day-start> --format=...
git show --format=fuller --stat --patch <sha>
git diff --no-ext-diff
git diff --cached --no-ext-diff
git status --short
```

每个提交输出 `sha`、`author_date`、`commit_date`、`subject`、`diff`。工作区同时输出已暂存、未暂存和受限的未跟踪文本内容；敏感文件与符号链接不读取。

- [ ] **Step 4: Implement previous/current review lookup**

按 `^(\d+)-(\d{4}-\d{2}-\d{2})\.md$` 解析报告。目标日期已有文件时复用；否则使用最大序号加一，序号至少两位。读取目标日期之前最新一份报告全文。

- [ ] **Step 5: Implement CLI and evidence status**

CLI：

```bash
python3 skills/daily-review/scripts/collect_context.py \
  --project . \
  --timezone Asia/Shanghai \
  [--date YYYY-MM-DD] \
  [--codex-home PATH]
```

输出 UTF-8 JSON，并提供：

```json
{
  "has_reviewable_evidence": true,
  "evidence_counts": {
    "conversations": 1,
    "commits": 1,
    "working_tree_changed": true
  }
}
```

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```bash
python3 -m unittest skills/daily-review/tests/test_collect_context.py -v
```

Expected: all tests pass.

### Task 3: Skill Workflow

**Files:**
- Create: `skills/daily-review/SKILL.md`
- Create: `skills/daily-review/agents/openai.yaml`

- [ ] **Step 1: Initialize the skill**

Run:

```bash
python3 /Users/bytedance/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  daily-review \
  --path skills \
  --resources scripts \
  --interface display_name="Daily Review" \
  --interface short_description="Review today's project learning with a rigorous interview" \
  --interface default_prompt="Use $daily-review to review today's work and test my understanding."
```

如果 Task 2 已先创建目录，则跳过初始化，仅用生成器创建 `agents/openai.yaml`。

- [ ] **Step 2: Write the evidence-first workflow**

`SKILL.md` 必须要求：

```markdown
1. 运行 `scripts/collect_context.py --project <current-root>`。
2. 没有有效证据时停止，不提问、不评分。
3. 先阅读上一份 TODO，再从当天证据提炼 5–8 个核心问题。
4. 每次只问一个问题；每题最多追问 2 次。
5. 完成全部面试前禁止提前公布分数。
```

- [ ] **Step 3: Write scoring rules**

固定维度：

```text
技术理解 40
独立思考 30
推理与表达 15
知识迁移 10
学习闭环 5
```

只依据面试回答评分。每个扣分必须引用具体回答或缺失点，提交量、代码量和主观努力不得加分。

- [ ] **Step 4: Write report rules**

写入采集结果给出的 `report.current_path`。同一天覆盖更新，新日期使用下一全局序号。报告必须包含证据摘要、问答结论、分项扣分、已掌握内容、薄弱点、上一份 TODO 状态和可验证的新 TODO。禁止自动执行 Git 提交。

- [ ] **Step 5: Validate skill metadata**

Run:

```bash
python3 /Users/bytedance/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/daily-review
```

Expected: `Skill is valid!`

### Task 4: Behavioral And End-To-End Verification

**Files:**
- Verify: `skills/daily-review/SKILL.md`
- Verify: `skills/daily-review/scripts/collect_context.py`

- [ ] **Step 1: Run a baseline agent scenario without the skill**

给独立 Agent 提供当天证据，要求复盘，记录它是否一次抛出多题、依据提交直接打分、忽略上一份 TODO 或在证据不足时编造问题。

- [ ] **Step 2: Run the same scenario with the skill**

断言 Agent：

- 首次回复只包含一个问题
- 问题引用当天真实证据
- 不提前评分
- 能根据回答追问
- 上一份 TODO 被纳入检查

- [ ] **Step 3: Run collector against the real project**

Run:

```bash
python3 skills/daily-review/scripts/collect_context.py \
  --project . \
  --timezone Asia/Shanghai > /tmp/daily-review-context.json
python3 -m json.tool /tmp/daily-review-context.json >/dev/null
```

Expected: exit 0 and valid JSON.

- [ ] **Step 4: Run all verification commands**

Run:

```bash
python3 -m unittest discover -s skills/daily-review/tests -v
python3 /Users/bytedance/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/daily-review
git diff --check -- skills/daily-review docs/superpowers/specs/2026-06-05-daily-review-skill-design.md docs/superpowers/plans/2026-06-05-daily-review-skill.md
```

Expected: tests pass, skill valid, and no whitespace errors.
