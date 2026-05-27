# Visual Companion 指南

这是一个基于浏览器的可视化 brainstorming companion，用于展示 mockup、diagram 和各种选项。

## 何时使用

按“每个问题”决定，而不是按“整个会话”决定。判断标准是：**用户看见它，是否会比读它更容易理解？**

当内容本身具有视觉性时，**使用 browser**：

- **UI mockup** —— wireframe、layout、navigation structure、component design
- **Architecture diagram** —— system component、data flow、relationship map
- **并排视觉对比** —— 比较两种 layout、两种 color scheme、两种 design direction
- **设计润色** —— 当问题聚焦于 look and feel、spacing、visual hierarchy 时
- **空间关系** —— 用 diagram 渲染的 state machine、flowchart、entity relationship

当内容是文本或表格时，**使用 terminal**：

- **需求与范围问题** —— “X 是什么意思？”、“哪些 feature 在 scope 内？”
- **概念性的 A/B/C 选择** —— 在文字描述的不同方案间做选择
- **Tradeoff 列表** —— 优缺点、对比表
- **技术决策** —— API design、data modeling、architecture approach 选择
- **澄清问题** —— 任何答案本质上是文字，而不是视觉偏好的内容

一个“关于 UI 主题”的问题，并不会自动变成视觉问题。“你想要哪种 wizard？”是概念问题——用 terminal。“这些 wizard layout 里哪一种看起来更合适？”才是视觉问题——用 browser。

## 工作原理

server 会监视一个目录中的 HTML 文件，并把最新的那个提供给 browser。你把 HTML 内容写到 `screen_dir`，用户就在 browser 里看到它，并可以通过点击来选择选项。用户的选择会记录到 `state_dir/events`，你在下一轮中读取它。

**内容片段 vs 完整文档：** 如果你的 HTML 文件以 `<!DOCTYPE` 或 `<html` 开头，server 会原样提供它（只会注入 helper script）。否则，server 会自动用 frame template 包裹你的内容——加入 header、CSS theme、selection indicator，以及全部交互基础设施。**默认写内容片段。** 只有在你需要完全控制页面时，才写完整文档。

## 启动一个会话

```bash
# Start server with persistence (mockups saved to project)
scripts/start-server.sh --project-dir /path/to/project

# Returns: {"type":"server-started","port":52341,"url":"http://localhost:52341",
#           "screen_dir":"/path/to/project/.superpowers/brainstorm/12345-1706000000/content",
#           "state_dir":"/path/to/project/.superpowers/brainstorm/12345-1706000000/state"}
```

从响应里保存 `screen_dir` 和 `state_dir`。然后告诉用户去打开该 URL。

**查找连接信息：** server 会把启动时的 JSON 写到 `$STATE_DIR/server-info`。如果你在后台启动了 server 却没有捕获 stdout，就读取这个文件来获取 URL 和 port。使用 `--project-dir` 时，到 `<project>/.superpowers/brainstorm/` 下查找 session 目录。

**注意：** 传入项目根目录作为 `--project-dir`，这样 mockup 会持久化到 `.superpowers/brainstorm/` 中，并在 server 重启后保留。如果不传，文件会落到 `/tmp` 并被清理掉。如果 `.superpowers/` 还没在 `.gitignore` 中，记得提醒用户加上。

**按平台启动 server：**

**Claude Code (macOS / Linux)：**
```bash
# Default mode works — the script backgrounds the server itself
scripts/start-server.sh --project-dir /path/to/project
```

**Claude Code (Windows)：**
```bash
# Windows auto-detects and uses foreground mode, which blocks the tool call.
# Use run_in_background: true on the Bash tool call so the server survives
# across conversation turns.
scripts/start-server.sh --project-dir /path/to/project
```
当你通过 Bash tool 调用它时，请设置 `run_in_background: true`。然后在下一轮读取 `$STATE_DIR/server-info` 来获取 URL 和 port。

**Codex：**
```bash
# Codex reaps background processes. The script auto-detects CODEX_CI and
# switches to foreground mode. Run it normally — no extra flags needed.
scripts/start-server.sh --project-dir /path/to/project
```

**Gemini CLI：**
```bash
# Use --foreground and set is_background: true on your shell tool call
# so the process survives across turns
scripts/start-server.sh --project-dir /path/to/project --foreground
```

**其他环境：** server 必须在多轮对话之间保持后台运行。如果你的环境会回收 detached process，请使用 `--foreground`，并借助你所在平台的后台执行机制来启动该命令。

如果 URL 在你的 browser 中不可达（这在 remote / containerized 环境里很常见），请绑定到一个非 loopback host：

```bash
scripts/start-server.sh \
  --project-dir /path/to/project \
  --host 0.0.0.0 \
  --url-host localhost
```

使用 `--url-host` 可以控制返回的 URL JSON 中打印出来的 hostname。

## 循环流程

1. **检查 server 仍然存活**，然后**把 HTML 写入** `screen_dir` 中的一个新文件：
   - 每次写入前，检查 `$STATE_DIR/server-info` 是否存在。如果不存在（或存在 `$STATE_DIR/server-stopped`），说明 server 已关闭——继续之前先用 `start-server.sh` 重启。server 会在 30 分钟无活动后自动退出。
   - 使用有语义的文件名：`platform.html`、`visual-style.html`、`layout.html`
   - **不要复用文件名** —— 每个 screen 都要使用全新的文件
   - 使用 Write tool —— **绝不要使用 cat/heredoc**（会把噪音输出到 terminal）
   - server 会自动提供最新的文件

2. **告诉用户会看到什么，并结束这一轮：**
   - 提醒他们 URL 是什么（每一步都提醒，而不只是第一次）
   - 用简短文字概述屏幕内容（例如：“正在展示 homepage 的 3 种 layout 选项”）
   - 请他们在 terminal 中回复：“看一下，然后告诉我你的想法。如果你愿意，也可以点击选择一个选项。”

3. **在下一轮** —— 用户在 terminal 里回复之后：
   - 如果 `$STATE_DIR/events` 存在，就读取它——里面保存了用户在 browser 中的交互（点击、选择），格式是 JSON lines
   - 将其与用户的 terminal 文本反馈合并起来，获得完整信息
   - terminal 消息是主反馈来源；`state_dir/events` 提供结构化交互数据

4. **迭代或前进** —— 如果反馈改变了当前 screen，就写一个新文件（例如 `layout-v2.html`）。只有在当前步骤得到验证后，才进入下一个问题。

5. **返回 terminal 时先卸载画面** —— 当下一步不再需要 browser（例如澄清问题、tradeoff 讨论）时，推送一个 waiting screen 来清除陈旧内容：

   ```html
   <!-- filename: waiting.html (or waiting-2.html, etc.) -->
   <div style="display:flex;align-items:center;justify-content:center;min-height:60vh">
     <p class="subtitle">Continuing in terminal...</p>
   </div>
   ```

   这样可以避免用户盯着一个已经结束的选择界面，而对话其实已经推进了。等下一个视觉问题出现时，再像平常一样推送新的内容文件。

6. 重复以上流程，直到完成。

## 编写内容片段

只编写页面内部的内容即可。server 会自动用 frame template 将其包裹起来（包括 header、theme CSS、selection indicator，以及全部交互基础设施）。

**最小示例：**

```html
<h2>Which layout works better?</h2>
<p class="subtitle">Consider readability and visual hierarchy</p>

<div class="options">
  <div class="option" data-choice="a" onclick="toggleSelect(this)">
    <div class="letter">A</div>
    <div class="content">
      <h3>Single Column</h3>
      <p>Clean, focused reading experience</p>
    </div>
  </div>
  <div class="option" data-choice="b" onclick="toggleSelect(this)">
    <div class="letter">B</div>
    <div class="content">
      <h3>Two Column</h3>
      <p>Sidebar navigation with main content</p>
    </div>
  </div>
</div>
```

就是这样。不需要 `<html>`、不需要 CSS、也不需要 `<script>` 标签。server 会提供这一切。

## 可用的 CSS Class

frame template 会为你的内容提供以下 CSS class：

### 选项（A/B/C 选择）

```html
<div class="options">
  <div class="option" data-choice="a" onclick="toggleSelect(this)">
    <div class="letter">A</div>
    <div class="content">
      <h3>Title</h3>
      <p>Description</p>
    </div>
  </div>
</div>
```

**多选：** 在容器上添加 `data-multiselect`，允许用户选择多个选项。每次点击都会切换该项的选中状态。indicator bar 会显示数量。

```html
<div class="options" data-multiselect>
  <!-- same option markup — users can select/deselect multiple -->
</div>
```

### 卡片（visual design）

```html
<div class="cards">
  <div class="card" data-choice="design1" onclick="toggleSelect(this)">
    <div class="card-image"><!-- mockup content --></div>
    <div class="card-body">
      <h3>Name</h3>
      <p>Description</p>
    </div>
  </div>
</div>
```

### Mockup 容器

```html
<div class="mockup">
  <div class="mockup-header">Preview: Dashboard Layout</div>
  <div class="mockup-body"><!-- your mockup HTML --></div>
</div>
```

### 分栏视图（side-by-side）

```html
<div class="split">
  <div class="mockup"><!-- left --></div>
  <div class="mockup"><!-- right --></div>
</div>
```

### 优缺点

```html
<div class="pros-cons">
  <div class="pros"><h4>Pros</h4><ul><li>Benefit</li></ul></div>
  <div class="cons"><h4>Cons</h4><ul><li>Drawback</li></ul></div>
</div>
```

### Mock 元素（wireframe building block）

```html
<div class="mock-nav">Logo | Home | About | Contact</div>
<div style="display: flex;">
  <div class="mock-sidebar">Navigation</div>
  <div class="mock-content">Main content area</div>
</div>
<button class="mock-button">Action Button</button>
<input class="mock-input" placeholder="Input field">
<div class="placeholder">Placeholder area</div>
```

### Typography 与 section

- `h2` —— 页面标题
- `h3` —— section 标题
- `.subtitle` —— 标题下方的次级说明文字
- `.section` —— 带底部间距的内容块
- `.label` —— 小号大写 label 文本

## Browser 事件格式

当用户在 browser 中点击选项时，他们的交互会被记录到 `$STATE_DIR/events`（每行一个 JSON object）。当你推送新 screen 时，该文件会被自动清空。

```jsonl
{"type":"click","choice":"a","text":"Option A - Simple Layout","timestamp":1706000101}
{"type":"click","choice":"c","text":"Option C - Complex Grid","timestamp":1706000108}
{"type":"click","choice":"b","text":"Option B - Hybrid","timestamp":1706000115}
```

完整的 event stream 会展示用户的探索路径——他们可能会点击多个选项之后才最终定下来。最后一个 `choice` event 通常是最终选择，但点击模式本身也可能反映出犹豫或偏好，值得进一步追问。

如果 `$STATE_DIR/events` 不存在，说明用户没有在 browser 中进行交互——这时只使用他们在 terminal 中的文字反馈。

## 设计建议

- **让保真度与问题匹配** —— layout 问题用 wireframe，polish 问题再做更精细的展示
- **每个页面都解释清楚问题** —— 比如“哪种 layout 看起来更专业？”而不是只写“选一个”
- **先迭代，再前进** —— 如果反馈改变了当前 screen，就先写一个新版本
- 每个 screen 最多 **2-4 个选项**
- **在重要时使用真实内容** —— 比如为摄影作品集设计时，使用真实图片（Unsplash）。占位内容会掩盖设计问题。
- **保持 mockup 简洁** —— 聚焦于 layout 和 structure，而不是 pixel-perfect design

## 文件命名

- 使用有语义的名称：`platform.html`、`visual-style.html`、`layout.html`
- 不要复用文件名 —— 每个 screen 都必须是一个新文件
- 对于迭代版本：追加版本后缀，比如 `layout-v2.html`、`layout-v3.html`
- server 会按修改时间提供最新文件

## 清理

```bash
scripts/stop-server.sh $SESSION_DIR
```

如果 session 使用了 `--project-dir`，mockup 文件会保留在 `.superpowers/brainstorm/` 中，便于后续参考。只有 `/tmp` session 才会在 stop 时被删除。

## 参考资料

- Frame template（CSS 参考）：`scripts/frame-template.html`
- Helper script（client-side）：`scripts/helper.js`
