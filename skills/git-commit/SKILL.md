---

name: git-commit
description: 用于按照本仓库约定执行 `git commit`。当用户表达"提交代码""帮我提交""commit 一下""git commit""生成 commit message""写提交信息""按仓库规范提交""提交当前改动"等意图时，必须优先使用此 skill，即使用户没有明确提到 skill 名称。它会先检查工作区变更与最近提交历史，再生成符合 Conventional Commits 风格的中文提交标题，并在变更不够琐碎时补充以 `- ` 开头的中文详细说明，然后只提交用户期望纳入本次提交的文件。提交成功后会询问用户是否需要推送到远程仓库。
---

# git-commit

按照本仓库约定的提交规范，帮助用户完成一次 `git commit`。

## 触发场景

- 用户说"提交""commit""帮我 commit""写个 commit message"
- 用户希望按仓库历史风格生成提交信息

## 提交信息规范

提交信息分为两部分：**标题**（必填）+ **详细信息**（可选，但变更复杂时必填）。

### 1. 标题（首行）

格式：`<type>(<scope>): <中文描述>`

- `type`：`feat`、`fix`、`refactor`、`docs`、`chore`、`style`、`test`、`perf` 等
- `scope`：可选，使用受影响的模块名，如 `PrdToolbar`、`DocView`
- `<中文描述>`：使用中文，动词开头，简洁准确，不加句号

**示例：**

- `chore: 忽略 .superpowers 本地临时产物`
- `refactor(PrdToolbar): 顶部操作区改为左对齐并调整入口顺序`
- `feat: add prd toolbar and assemble list page`
- `docs: add prd toolbar implementation plan`

### 2. 详细信息（body）

- 与标题之间空一行
- 使用以 `- `  开头的中文短句列举关键变更
- 每条聚焦一个事实或决策点，避免重复标题
- 非琐碎变更必须填写 body；琐碎且自解释的变更（如简单文档新增）可省略

**示例（来自仓库历史）：**

```
refactor(PrdToolbar): 顶部操作区改为左对齐并调整入口顺序

- 将顶部操作区容器由 justify-end 调整为 justify-start，整体内容靠左排列。
- 入口顺序由"搜索 / 导入已有 PRD / 新建 PRD"重排为"新建 PRD / 导入已有 PRD / 搜索框"，强化创建主入口的视觉位置。
- 仅调整顶部 Toolbar 主行布局与子项渲染顺序，弹窗结构、受控/非受控逻辑、事件透传与禁用规则保持不变。
- 同步更新 docs/superpowers/specs 与 docs/superpowers/plans 中的 PrdToolbar 设计与实施文档，描述与实现保持一致。
```

## 执行流程

1. **查看当前状态**（并行执行）：
   - `git status`（不要使用 `-uall`）
   - `git diff`（含已暂存与未暂存）
   - `git log -n 5 --oneline`（参考历史风格）
2. **分析变更**：
   - 判断变更性质，选择合适的 `type`
   - 识别主要受影响模块作为 `scope`
   - 提炼"为什么改"而不仅仅是"改了什么"
3. **草拟提交信息**：
   - 标题不超过 72 个字符
   - body 用 `- `  列出关键点，每条独立成句
   - 只有用户明确请求时才提交 `.env`、密钥等敏感文件
4. **执行提交**：
   - 仅添加用户期望提交的具体文件，避免 `git add -A` 或 `git add .`
   - 使用 HEREDOC 传递多行 commit message：
   ```bash
   git commit -m "$(cat <<'EOF'
   refactor(PrdToolbar): 顶部操作区改为左对齐并调整入口顺序

   - 将顶部操作区容器由 justify-end 调整为 justify-start。
   - 入口顺序重排为"新建 PRD / 导入已有 PRD / 搜索框"。
   EOF
   )"
   ```
5. **验证结果**：
   - `git status` 确认提交成功
6. **询问是否推送**：
   - 提交成功后，使用 `AskUserQuestion` 工具询问用户是否需要推送到远程仓库
   - 问题格式：是否需要将本次提交推送到远程仓库？
   - 选项：`推送 (git push)` / `暂不推送`
   - 若用户选择推送，执行 `git push`；若选择暂不推送，仅告知提交已完成
   - 若推送失败（如网络错误、权限问题），将错误信息反馈给用户，不自动重试

## 边界与禁忌

- **不要主动修改代码**：本 skill 仅负责生成提交信息并执行 `git commit`，不对工作区任何业务代码、配置、文档做修改。
  - 仅当发现会导致提交失败或引入明显错误的**重大问题**（如即将提交密钥/敏感文件、二进制大文件混入、明显冲突标记 `<<<<<<<` 残留、提交内容与用户描述严重不符）时，才考虑修改。
  - 即使遇到上述重大问题，**也必须先向用户清晰说明问题并征得明确同意后再修改**，禁止先斩后奏。
  - 格式化、lint 修复、重命名、重构、"顺手优化"、补注释等一律禁止。
- 未经用户明确许可，**不要** `reset --hard`、`push --force`
- 不要修改 `git config`
- 没有变更时（无未跟踪文件、无修改）**不要** 创建空提交
- 标题与 body 全程使用与用户输入一致的语言（本仓库默认中文）
