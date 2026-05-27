# Creation Log: Systematic Debugging Skill

关于如何提取、结构化并加固一个关键 skill 的参考示例。

## 源材料

从 `~/.claude/CLAUDE.md` 中提取出的调试框架：
- 四阶段系统化流程（Investigation → Pattern Analysis → Hypothesis → Implementation）
- 核心要求：始终找到 root cause，绝不只修 symptom
- 规则设计用于抵抗时间压力和自我合理化

## 提取决策

**应纳入的内容：**
- 完整的四阶段框架及其全部规则
- 反捷径规则（“NEVER fix symptom”、“STOP and re-analyze”）
- 抗压语言（“even if faster”、“even if I seem in a hurry”）
- 每个阶段的具体步骤

**应排除的内容：**
- 项目特定上下文
- 同一规则的重复变体
- 叙述性解释（浓缩为原则）

## 遵循 skill-creation/SKILL.md 的结构

1. **丰富的 when_to_use** - 纳入症状与 anti-patterns
2. **Type: technique** - 带步骤的具体流程
3. **关键词** - “root cause”、“symptom”、“workaround”、“debugging”、“investigation”
4. **流程图** - 关于“fix failed”后应 re-analyze 还是继续加更多 fix 的决策点
5. **按阶段拆解** - 便于快速扫描的 checklist 形式
6. **Anti-patterns 部分** - 明确列出不要做什么（这对本 skill 很关键）

## 加固元素

该框架被设计成在压力下也能抵抗自我合理化：

### 语言选择
- “ALWAYS” / “NEVER”（而不是 “should” / “try to”）
- “even if faster” / “even if I seem in a hurry”
- “STOP and re-analyze”（显式暂停）
- “Don't skip past”（抓住真实会发生的行为）

### 结构性防线
- **必须经过 Phase 1** - 不能直接跳到 implementation
- **单一假设规则** - 强迫思考，防止 shotgun fixes
- **显式失败分支** - “IF your first fix doesn't work” 并配有强制动作
- **Anti-patterns 部分** - 准确展示捷径长什么样

### 冗余设计
- Root cause 要求在 overview、when_to_use、Phase 1 和 implementation rules 中重复出现
- “NEVER fix symptom” 在不同上下文中出现了 4 次
- 每个阶段都有明确的“不要跳过”指导

## 测试方式

按照 skills/meta/testing-skills-with-subagents 创建了 4 个验证测试：

### Test 1: 学术场景（无压力）
- 简单 bug，无时间压力
- **结果：** 完全遵循，调查完整

### Test 2: 时间压力 + 明显的 quick fix
- 用户“很着急”，symptom fix 看起来很容易
- **结果：** 抵制了捷径，遵循完整流程，找到了真正的 root cause

### Test 3: 复杂系统 + 不确定性
- 多层级故障，不清楚是否能找到 root cause
- **结果：** 系统化调查，穿透所有层级完成追踪，找到了源头

### Test 4: 第一次 fix 失败
- 假设不成立，容易诱发继续叠加 fix
- **结果：** 停下、重新分析、提出新假设（没有 shotgun）

**全部测试通过。** 未发现任何合理化捷径。

## 迭代

### 初始版本
- 完整的四阶段框架
- Anti-patterns 部分
- 针对 “fix failed” 决策的流程图

### 增强 1: TDD 引用
- 添加了指向 skills/testing/test-driven-development 的链接
- 增加说明，解释 TDD 的 “simplest code” 与 debugging 的 “root cause” 不相同
- 防止两种方法论混淆

## 最终结果

一个足够稳固的 skill，它：
- ✅ 明确要求 root cause investigation
- ✅ 能抵抗时间压力下的自我合理化
- ✅ 为每个阶段提供具体步骤
- ✅ 明确展示 anti-patterns
- ✅ 在多种压力场景下经过测试
- ✅ 澄清了与 TDD 的关系
- ✅ 已可投入使用

## 关键洞察

**最重要的加固点：** Anti-patterns 部分直接展示那些在当下看似“有道理”的捷径。当 Claude 心里冒出“我就先加一个 quick fix”的念头时，看到这个模式已被明确列为错误，会形成认知阻力。

## 使用示例

当遇到 bug 时：
1. 加载 skill：skills/debugging/systematic-debugging
2. 阅读 overview（10 秒）- 重新提醒自己必须遵守的要求
3. 按照 Phase 1 checklist 执行 - 被迫先调查
4. 如果想跳过 - 看到 anti-pattern，立即停下
5. 完成所有阶段 - 找到 root cause

**投入时间：** 5-10 分钟
**节省时间：** 避免数小时的 symptom-whack-a-mole

---

*Created: 2025-10-03*
*Purpose: Reference example for skill extraction and bulletproofing*
