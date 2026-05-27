# Code Quality Reviewer Prompt Template

在分派 code quality reviewer subagent 时使用此模板。

**目的：** 验证实现是否构建得当（整洁、经过测试、可维护）

**只有在 spec compliance review 通过后才能分派。**

```
Task tool (general-purpose):
  Use template at requesting-code-review/code-reviewer.md

  DESCRIPTION: [task summary, from implementer's report]
  PLAN_OR_REQUIREMENTS: Task N from [plan-file]
  BASE_SHA: [commit before task]
  HEAD_SHA: [current commit]
```

**除了标准的 code quality 关注点外，reviewer 还应检查：**
- 每个文件是否都只有一个清晰职责，并具备定义明确的接口？
- 各个单元是否被拆解到可以被独立理解和测试？
- 实现是否遵循了计划中的文件结构？
- 这次实现是否创建了本来就很大的新文件，或显著增大了现有文件？（不要标记既有文件原本的大小——只关注这次变更带来的影响。）

**Code reviewer 返回内容：** Strengths、Issues（Critical/Important/Minor）、Assessment
