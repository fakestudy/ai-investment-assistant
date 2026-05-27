# Persuasion Principles for Skill Design

## Overview

LLMs 对说服原则的反应与人类相似。理解这种心理学能帮助你设计出更有效的 skills —— 目的不是操控，而是确保关键实践即使在压力下也会被遵循。

**Research foundation:** Meincke et al. (2025) 在 N=28,000 次 AI 对话中测试了 7 种说服原则。说服技巧让合规率提升了两倍多（33% → 72%，p < .001）。

## The Seven Principles

### 1. Authority
**What it is:** 对专业性、资历或官方来源的服从。

**How it works in skills:**
- 命令式语言：`YOU MUST`、`Never`、`Always`
- 不可协商式 framing：`No exceptions`
- 消除决策疲劳和自我合理化

**When to use:**
- 强化纪律的 skills（TDD、verification requirements）
- 安全关键实践
- 已被验证的最佳实践

**Example:**
```markdown
✅ Write code before test? Delete it. Start over. No exceptions.
❌ Consider writing tests first when feasible.
```

### 2. Commitment
**What it is:** 与先前行为、表态或公开声明保持一致。

**How it works in skills:**
- 要求 announcement：`Announce skill usage`
- 强制明确选择：`Choose A, B, or C`
- 使用追踪：TodoWrite 做 checklist

**When to use:**
- 确保 skills 被真正遵循
- 多步骤流程
- 可追责机制

**Example:**
```markdown
✅ When you find a skill, you MUST announce: "I'm using [Skill Name]"
❌ Consider letting your partner know which skill you're using.
```

### 3. Scarcity
**What it is:** 由时间限制或稀缺性带来的紧迫感。

**How it works in skills:**
- 带时间约束的要求：`Before proceeding`
- 顺序依赖：`Immediately after X`
- 防止拖延

**When to use:**
- 需要立刻验证的要求
- 时间敏感型工作流
- 防止“我之后再做”

**Example:**
```markdown
✅ After completing a task, IMMEDIATELY request code review before proceeding.
❌ You can review code when convenient.
```

### 4. Social Proof
**What it is:** 对“别人都这么做”或“这是常态”的从众反应。

**How it works in skills:**
- 普遍性表述：`Every time`、`Always`
- 失败模式：`X without Y = failure`
- 建立规范感

**When to use:**
- 记录普适实践
- 警告常见失败模式
- 强化标准

**Example:**
```markdown
✅ Checklists without TodoWrite tracking = steps get skipped. Every time.
❌ Some people find TodoWrite helpful for checklists.
```

### 5. Unity
**What it is:** 共享身份感、同伴感、“我们”的感觉。

**How it works in skills:**
- 协作式语言：`our codebase`、`we're colleagues`
- 共享目标：`we both want quality`

**When to use:**
- 协作型工作流
- 建立团队文化
- 非层级式实践

**Example:**
```markdown
✅ We're colleagues working together. I need your honest technical judgment.
❌ You should probably tell me if I'm wrong.
```

### 6. Reciprocity
**What it is:** 因为接受了好处而产生回报义务。

**How it works:**
- 谨慎使用 —— 很容易显得在操控
- 在 skills 中很少需要

**When to avoid:**
- 几乎总是应避免（其他原则更有效）

### 7. Liking
**What it is:** 更愿意与自己喜欢的对象合作。

**How it works:**
- **DON'T USE 用于合规性要求**
- 会与诚实反馈文化冲突
- 会制造 sycophancy

**When to avoid:**
- 对纪律性约束来说，永远避免

## Principle Combinations by Skill Type

| Skill Type | Use | Avoid |
|------------|-----|-------|
| Discipline-enforcing | Authority + Commitment + Social Proof | Liking, Reciprocity |
| Guidance/technique | Moderate Authority + Unity | Heavy authority |
| Collaborative | Unity + Commitment | Authority, Liking |
| Reference | 只要清晰即可 | 所有 persuasion |

## Why This Works: The Psychology

**明亮边界规则可以减少自我合理化：**
- `YOU MUST` 消除了决策疲劳
- 绝对性语言消除了“这算不算例外？”
- 明确的 anti-rationalization 反制堵住了具体漏洞

**实施意图会形成自动行为：**
- 明确 trigger + 明确动作 = 自动执行
- “When X, do Y” 比 “通常做 Y” 更有效
- 降低合规所需的认知负荷

**LLMs 是 parahuman：**
- 它们在训练语料中学习了人类文本中的这些模式
- authority 语言通常先于服从出现
- commitment 序列（statement → action）被频繁建模
- social proof 模式（everyone does X）会建立规范

## Ethical Use

**正当用途：**
- 确保关键实践被遵守
- 编写更有效的文档
- 防止可预测的失败

**不正当用途：**
- 为个人利益操控
- 制造虚假紧迫感
- 用内疚感强迫合规

**检验标准：** 如果用户完全理解这种技巧，它仍然会服务于用户的真实利益吗？

## Research Citations

**Cialdini, R. B. (2021).** *Influence: The Psychology of Persuasion (New and Expanded).* Harper Business.
- 说服的七大原则
- 影响力研究的实证基础

**Meincke, L., Shapiro, D., Duckworth, A. L., Mollick, E., Mollick, L., & Cialdini, R. (2025).** Call Me A Jerk: Persuading AI to Comply with Objectionable Requests. University of Pennsylvania.
- 在 N=28,000 次 LLM 对话中测试了 7 种原则
- 使用说服技巧后，合规率从 33% 提升到 72%
- Authority、commitment、scarcity 最有效
- 验证了 LLM 行为的 parahuman 模型

## Quick Reference

设计 skill 时，问自己：

1. **它属于什么类型？**（Discipline vs. guidance vs. reference）
2. **我想改变什么行为？**
3. **适用哪些原则？**（纪律类通常是 authority + commitment）
4. **我是不是叠加太多了？**（不要把七种全用上）
5. **这是否符合伦理？**（是否服务于用户的真实利益？）
