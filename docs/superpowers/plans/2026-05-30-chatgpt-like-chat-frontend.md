# ChatGPT-like 聊天前端实施计划

> **给执行 Agent 的要求：** 实施本计划时，必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项执行。所有步骤使用 `- [ ]` 复选框便于追踪。

**目标：** 仅实现前端部分，把当前默认首页改造成桌面端优先、浅色主题、ChatGPT 风格的聊天界面。

**架构：** `web/app/page.tsx` 只负责挂载聊天入口，具体功能放到 `web/features/chat/`。前端负责页面布局、UI 状态、REST 请求、SSE 流消费、消息渲染和用户交互；后端负责模型调用、会话持久化、标题生成和工具执行。

**技术栈：** Next.js 16 App Router、React 19、TypeScript、Tailwind CSS v4、shadcn/ui、现有 `components/ai-elements/*`、`zustand`、`lucide-react`、原生 `fetch` 和 `ReadableStream`。

---

## 1. 范围

只做前端，不做后端。

本期做：

- ChatGPT 风格桌面布局。
- 左侧会话栏。
- 中间消息区。
- 底部输入框。
- 会话 CRUD 的前端调用。
- SSE 流式消息消费。
- Markdown / Code / reasoning / tool 调用展示。
- 复制、重新生成、点赞、点踩、编辑用户消息。
- 错误提示和加载态。

本期不做：

- 不做投资业务。
- 不做文件上传、图片上传、附件入口。
- 不做模型切换 UI。
- 不做登录、注册、多用户。
- 不做移动端专项适配。
- 不做会话搜索、分享、归档。
- 不做语音输入、Canvas、GPTs、Projects。
- 不做暗色主题。
- 不做消息分支版本。

---

## 2. 后端接口假设

前端先按下面接口写适配层。后端路径后续如果调整，只改 `web/features/chat/api.ts`。

```ts
export const CHAT_API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";
```

REST 接口：

```txt
GET    /api/conversations
POST   /api/conversations
PATCH  /api/conversations/:conversationId
DELETE /api/conversations/:conversationId
GET    /api/conversations/:conversationId/messages
PATCH  /api/messages/:messageId
POST   /api/chat/stream
```

SSE 事件：

```ts
type ChatStreamEvent =
  | { type: "message_created"; message: ChatMessage }
  | { type: "delta"; messageId: string; text: string }
  | { type: "reasoning"; messageId: string; text: string }
  | { type: "tool_call"; messageId: string; invocation: ToolInvocation }
  | { type: "tool_result"; messageId: string; invocation: ToolInvocation }
  | { type: "title"; conversationId: string; title: string }
  | { type: "done"; messageId: string }
  | { type: "error"; messageId?: string; message: string };
```

---

## 3. 文件规划

新增：

- `web/features/chat/types.ts`：聊天类型。
- `web/features/chat/api.ts`：REST 和 SSE 适配。
- `web/features/chat/store.ts`：Zustand 状态管理。
- `web/features/chat/components/chat-shell.tsx`：页面总壳。
- `web/features/chat/components/chat-sidebar.tsx`：左侧会话栏。
- `web/features/chat/components/chat-main.tsx`：右侧主区域。
- `web/features/chat/components/chat-message-list.tsx`：消息列表。
- `web/features/chat/components/chat-message-item.tsx`：单条消息。
- `web/features/chat/components/chat-input.tsx`：底部输入框。
- `web/features/chat/components/tool-invocation-card.tsx`：工具调用详情。
- `web/features/chat/components/delete-conversation-dialog.tsx`：删除确认弹窗。
- `web/features/chat/components/rename-conversation-dialog.tsx`：重命名弹窗。

修改：

- `web/app/page.tsx`：替换默认模板，挂载 `ChatShell`。
- `web/app/layout.tsx`：更新页面标题和描述。

复用：

- `web/components/ai-elements/conversation.tsx`
- `web/components/ai-elements/message.tsx`
- `web/components/ai-elements/reasoning.tsx`
- `web/components/ai-elements/tool.tsx`
- `web/components/ai-elements/code-block.tsx`
- `web/components/ui/*`

---

## 任务 1：定义前端聊天类型

**文件：**

- 新建：`web/features/chat/types.ts`

- [ ] **步骤 1：写入类型定义**

```ts
export type ChatRole = "user" | "assistant" | "tool";

export type Conversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
};

export type MessageStatus = "idle" | "streaming" | "done" | "error";
export type ToolInvocationStatus = "running" | "completed" | "error";

export type ToolInvocation = {
  id: string;
  messageId: string;
  toolName: "web_search" | "fetch_url" | string;
  args: Record<string, unknown>;
  result?: unknown;
  error?: string;
  latencyMs?: number;
  status: ToolInvocationStatus;
  createdAt?: string;
};

export type ChatMessage = {
  id: string;
  conversationId: string;
  role: ChatRole;
  content: string;
  reasoning?: string;
  toolInvocations?: ToolInvocation[];
  status?: MessageStatus;
  createdAt: string;
};

export type StreamChatRequest = {
  conversationId: string;
  message: string;
  parentMessageId?: string;
  regenerateFromMessageId?: string;
};

export type ChatStreamEvent =
  | { type: "message_created"; message: ChatMessage }
  | { type: "delta"; messageId: string; text: string }
  | { type: "reasoning"; messageId: string; text: string }
  | { type: "tool_call"; messageId: string; invocation: ToolInvocation }
  | { type: "tool_result"; messageId: string; invocation: ToolInvocation }
  | { type: "title"; conversationId: string; title: string }
  | { type: "done"; messageId: string }
  | { type: "error"; messageId?: string; message: string };

export type ChatError = {
  message: string;
  scope: "conversation" | "message" | "stream";
};
```

- [ ] **步骤 2：验证**

```bash
cd web
pnpm lint
```

预期：退出码为 `0`。

- [ ] **步骤 3：提交**

```bash
git add web/features/chat/types.ts
git commit -m "feat(chat): 定义前端聊天数据类型"
```

---

## 任务 2：实现前端 API 适配层

**文件：**

- 新建：`web/features/chat/api.ts`

- [ ] **步骤 1：实现 REST 方法**

需要导出这些方法：

```ts
listConversations(): Promise<Conversation[]>
createConversation(): Promise<Conversation>
renameConversation(conversationId: string, title: string): Promise<Conversation>
deleteConversation(conversationId: string): Promise<void>
listMessages(conversationId: string): Promise<ChatMessage[]>
editMessage(messageId: string, content: string): Promise<ChatMessage>
```

要求：

- 所有请求都基于 `CHAT_API_BASE`。
- JSON 请求统一带 `Content-Type: application/json`。
- 非 `2xx` 响应要抛出 `Error`。

- [ ] **步骤 2：实现 SSE 方法**

需要导出：

```ts
streamChat(
  request: StreamChatRequest,
  options: {
    signal: AbortSignal;
    onEvent: (event: ChatStreamEvent) => void;
  }
): Promise<void>
```

要求：

- 使用 `fetch` 发起 `POST /api/chat/stream`。
- 使用 `response.body.getReader()` 读取流。
- 使用 `TextDecoder` 解码。
- 按 `\n\n` 拆分 SSE event。
- 只解析 `data:` 行。
- 解析后调用 `options.onEvent(event)`。
- 支持 `AbortSignal` 中断。

- [ ] **步骤 3：验证**

```bash
cd web
pnpm lint
pnpm build
```

预期：两个命令退出码都为 `0`。

- [ ] **步骤 4：提交**

```bash
git add web/features/chat/api.ts
git commit -m "feat(chat): 添加前端聊天 API 客户端"
```

---

## 任务 3：实现 Zustand 聊天状态管理

**文件：**

- 新建：`web/features/chat/store.ts`

- [ ] **步骤 1：创建 store 状态**

状态字段：

```ts
conversations: Conversation[]
activeConversationId?: string
messagesByConversationId: Record<string, ChatMessage[]>
isLoadingConversations: boolean
isLoadingMessages: boolean
isStreaming: boolean
error?: ChatError
abortController?: AbortController
```

- [ ] **步骤 2：创建 store 方法**

方法列表：

```ts
loadConversations(): Promise<void>
createNewConversation(): Promise<void>
selectConversation(conversationId: string): Promise<void>
renameActiveConversation(title: string): Promise<void>
deleteActiveConversation(): Promise<void>
sendMessage(content: string): Promise<void>
stopStreaming(): void
regenerateLastAssistantMessage(): Promise<void>
editUserMessageAndRegenerate(messageId: string, content: string): Promise<void>
clearError(): void
```

- [ ] **步骤 3：处理 SSE 事件**

事件处理规则：

- `message_created`：插入或更新消息。
- `delta`：追加到 assistant 消息 `content`。
- `reasoning`：追加到 assistant 消息 `reasoning`。
- `tool_call`：插入或更新工具调用。
- `tool_result`：插入或更新工具结果。
- `title`：更新会话标题。
- `done`：结束流式状态。
- `error`：结束流式状态并设置错误。

- [ ] **步骤 4：验证**

```bash
cd web
pnpm lint
pnpm build
```

预期：两个命令退出码都为 `0`。

- [ ] **步骤 5：提交**

```bash
git add web/features/chat/store.ts
git commit -m "feat(chat): 添加前端聊天状态管理"
```

---

## 任务 4：替换首页为聊天页面骨架

**文件：**

- 新建：`web/features/chat/components/chat-shell.tsx`
- 新建：`web/features/chat/components/chat-sidebar.tsx`
- 新建：`web/features/chat/components/chat-main.tsx`
- 修改：`web/app/page.tsx`
- 修改：`web/app/layout.tsx`

- [ ] **步骤 1：实现 `ChatShell`**

要求：

- 组件使用 `"use client"`。
- 首次挂载调用 `loadConversations()`。
- 页面结构为左侧 `ChatSidebar` + 右侧 `ChatMain`。
- 外层高度为 `h-screen`。
- 背景为浅色。

- [ ] **步骤 2：实现临时 `ChatSidebar`**

要求：

- 宽度 `260px`。
- 浅灰背景。
- 有 `New chat` 按钮。

- [ ] **步骤 3：实现临时 `ChatMain`**

要求：

- 顶部显示 `AI Chat Assistant`。
- 中间显示 `How can I help?`。

- [ ] **步骤 4：替换 `web/app/page.tsx`**

```tsx
import { ChatShell } from "@/features/chat/components/chat-shell";

export default function Home() {
  return <ChatShell />;
}
```

- [ ] **步骤 5：更新 `web/app/layout.tsx` metadata**

```ts
export const metadata: Metadata = {
  title: "AI Chat Assistant",
  description: "ChatGPT-like local AI chat assistant",
};
```

- [ ] **步骤 6：验证**

```bash
cd web
pnpm lint
pnpm build
```

预期：两个命令退出码都为 `0`。

- [ ] **步骤 7：提交**

```bash
git add web/app/page.tsx web/app/layout.tsx web/features/chat/components/chat-shell.tsx web/features/chat/components/chat-sidebar.tsx web/features/chat/components/chat-main.tsx
git commit -m "feat(chat): 接入桌面聊天页面骨架"
```

---

## 任务 5：实现左侧会话栏

**文件：**

- 修改：`web/features/chat/components/chat-sidebar.tsx`
- 新建：`web/features/chat/components/rename-conversation-dialog.tsx`
- 新建：`web/features/chat/components/delete-conversation-dialog.tsx`

- [ ] **步骤 1：会话栏功能**

必须支持：

- 新建会话。
- 展示会话列表。
- 高亮当前会话。
- 点击切换会话。
- 当前会话可重命名。
- 当前会话可删除。
- 删除前弹窗确认。

- [ ] **步骤 2：会话栏样式**

必须满足：

- 宽度固定 `260px`。
- 背景浅灰。
- 当前会话白色高亮。
- 不出现搜索入口。
- 不出现登录入口。

- [ ] **步骤 3：验证**

```bash
cd web
pnpm lint
pnpm build
```

预期：两个命令退出码都为 `0`。

- [ ] **步骤 4：提交**

```bash
git add web/features/chat/components/chat-sidebar.tsx web/features/chat/components/rename-conversation-dialog.tsx web/features/chat/components/delete-conversation-dialog.tsx
git commit -m "feat(chat): 实现会话侧栏管理"
```

---

## 任务 6：实现消息列表和单条消息

**文件：**

- 新建：`web/features/chat/components/chat-message-list.tsx`
- 新建：`web/features/chat/components/chat-message-item.tsx`
- 修改：`web/features/chat/components/chat-main.tsx`

- [ ] **步骤 1：消息列表**

复用：

- `Conversation`
- `ConversationContent`
- `ConversationEmptyState`
- `ConversationScrollButton`

要求：

- 消息区最大宽度 `max-w-3xl`。
- 空状态文案为 `How can I help?`。
- 消息加载中显示 `Loading messages...`。

- [ ] **步骤 2：单条消息**

用户消息：

- 靠右。
- 支持复制。
- 支持编辑。
- 编辑保存后调用 `editUserMessageAndRegenerate`。

assistant 消息：

- 靠左。
- 支持复制。
- 支持重新生成。
- 支持点赞。
- 支持点踩。
- 支持 reasoning 折叠展示。
- 支持 tool 详情展示。

- [ ] **步骤 3：验证**

```bash
cd web
pnpm lint
pnpm build
```

预期：两个命令退出码都为 `0`。

- [ ] **步骤 4：提交**

```bash
git add web/features/chat/components/chat-main.tsx web/features/chat/components/chat-message-list.tsx web/features/chat/components/chat-message-item.tsx
git commit -m "feat(chat): 实现聊天消息列表"
```

---

## 任务 7：实现底部输入框

**文件：**

- 新建或修改：`web/features/chat/components/chat-input.tsx`
- 修改：`web/features/chat/components/chat-main.tsx`

- [ ] **步骤 1：输入功能**

必须支持：

- 多行输入。
- `Enter` 发送。
- `Shift+Enter` 换行。
- 空内容禁用发送。
- 发送时调用 `sendMessage`。
- 流式生成时显示停止按钮。
- 停止按钮调用 `stopStreaming`。

禁止出现：

- 附件按钮。
- 上传按钮。
- 模型选择器。
- 语音按钮。

- [ ] **步骤 2：输入样式**

必须满足：

- 固定在主区域底部。
- 最大宽度与消息区一致。
- 容器使用 `rounded-3xl`。
- 浅色 ChatGPT 风格。
- 底部提示文案：`AI can make mistakes. Check important info.`

- [ ] **步骤 3：验证**

```bash
cd web
pnpm lint
pnpm build
```

预期：两个命令退出码都为 `0`。

- [ ] **步骤 4：提交**

```bash
git add web/features/chat/components/chat-input.tsx web/features/chat/components/chat-main.tsx
git commit -m "feat(chat): 实现聊天输入框交互"
```

---

## 任务 8：实现工具调用详情卡片

**文件：**

- 新建：`web/features/chat/components/tool-invocation-card.tsx`

- [ ] **步骤 1：展示内容**

必须展示：

- 工具名。
- 调用参数。
- 运行状态。
- 耗时。
- 结果摘要。
- 错误信息。

复用：

- `Tool`
- `ToolHeader`
- `ToolContent`
- `ToolInput`
- `ToolOutput`

- [ ] **步骤 2：状态映射**

```ts
function toToolState(status: ToolInvocation["status"]) {
  if (status === "running") return "input-available" as const;
  if (status === "error") return "output-error" as const;
  return "output-available" as const;
}
```

- [ ] **步骤 3：验证**

```bash
cd web
pnpm lint
pnpm build
```

预期：两个命令退出码都为 `0`。

- [ ] **步骤 4：提交**

```bash
git add web/features/chat/components/tool-invocation-card.tsx
git commit -m "feat(chat): 展示工具调用详情"
```

---

## 任务 9：补充错误提示和加载态

**文件：**

- 修改：`web/features/chat/components/chat-main.tsx`
- 修改：`web/features/chat/components/chat-message-list.tsx`
- 修改：`web/features/chat/components/chat-sidebar.tsx`

- [ ] **步骤 1：错误提示**

主区域顶部展示错误 banner：

- 显示 `error.message`。
- 有关闭按钮。
- 关闭时调用 `clearError`。
- 样式为浅红背景，不使用阻塞弹窗。

- [ ] **步骤 2：加载态**

会话加载中：

```txt
Loading chats...
```

消息加载中：

```txt
Loading messages...
```

空会话：

```txt
How can I help?
```

- [ ] **步骤 3：验证**

```bash
cd web
pnpm lint
pnpm build
```

预期：两个命令退出码都为 `0`。

- [ ] **步骤 4：提交**

```bash
git add web/features/chat/components/chat-main.tsx web/features/chat/components/chat-message-list.tsx web/features/chat/components/chat-sidebar.tsx
git commit -m "feat(chat): 添加聊天错误与加载状态"
```

---

## 任务 10：打磨 ChatGPT 风格

**文件：**

- 修改：`web/features/chat/components/chat-shell.tsx`
- 修改：`web/features/chat/components/chat-sidebar.tsx`
- 修改：`web/features/chat/components/chat-main.tsx`
- 修改：`web/features/chat/components/chat-input.tsx`
- 修改：`web/features/chat/components/chat-message-item.tsx`

- [ ] **步骤 1：视觉检查**

必须满足：

- 左侧栏宽度是 `260px`。
- 主区域背景是白色。
- 消息区最大宽度是 `max-w-3xl`。
- 输入框容器是 `rounded-3xl`。
- 新聊天功能文件不主动新增 `dark:` 样式。
- 整体是浅色、中性、低干扰风格。

- [ ] **步骤 2：范围检查**

新增聊天文件里不能出现这些入口：

```txt
Attach
Upload
Model
Login
Search chats
Share
Archive
Voice
Canvas
GPTs
Projects
```

如果出现，删除对应控件。

- [ ] **步骤 3：验证**

```bash
cd web
pnpm lint
pnpm build
```

预期：两个命令退出码都为 `0`。

- [ ] **步骤 4：浏览器检查**

```bash
cd web
pnpm dev
```

检查：

- 页面是桌面端 ChatGPT-like 布局。
- 左侧栏可见。
- 中间空状态显示 `How can I help?`。
- 底部输入框可输入。
- `Enter` 发送。
- `Shift+Enter` 换行。
- 没有文件上传、模型切换、登录等入口。

- [ ] **步骤 5：提交**

```bash
git add web/features/chat/components
git commit -m "style(chat): 打磨 ChatGPT 风格桌面界面"
```

---

## 任务 11：前端最终验收

**文件：**

- 只在发现问题时修改 `web/app/page.tsx`、`web/app/layout.tsx` 或 `web/features/chat/*`。

- [ ] **步骤 1：运行完整校验**

```bash
cd web
pnpm lint
pnpm build
```

预期：两个命令退出码都为 `0`。

- [ ] **步骤 2：逐项验收**

检查：

- 页面是 ChatGPT-like 浅色桌面布局。
- 左侧栏支持新建会话。
- 左侧栏支持切换会话。
- 左侧栏支持重命名会话。
- 左侧栏支持删除确认。
- 空状态只有欢迎语和输入框。
- 输入框支持多行输入。
- 输入框支持 `Enter` 发送。
- 输入框支持 `Shift+Enter` 换行。
- 空内容不能发送。
- 流式生成时按钮变成停止按钮。
- assistant 消息支持复制、重新生成、点赞、点踩。
- user 消息支持复制、编辑。
- reasoning 可以折叠展示。
- tool 详情展示工具名、参数、状态、耗时、结果、错误。
- 错误 banner 可见且可关闭。
- 不出现文件上传、模型切换、登录、搜索、分享、归档、语音、Canvas、GPTs、Projects。

- [ ] **步骤 3：提交最终修复**

如果有修复：

```bash
git add web/app/page.tsx web/app/layout.tsx web/features/chat
git commit -m "fix(chat): 修正前端聊天验收问题"
```

如果没有修复，不创建空提交。

---

## 4. 自检结果

- 已覆盖前端职责：布局、主题、空状态、会话管理、输入、消息展示、编辑、reasoning、工具展示、错误处理、验收。
- 已明确排除非本期范围：后端、投资业务、上传、模型切换、登录、移动端、搜索、分享、归档、语音、Canvas、GPTs、Projects、暗色主题、消息分支。
- 类型命名保持一致：`Conversation`、`ChatMessage`、`ToolInvocation`、`ChatStreamEvent`、`useChatStore`。
- 每个任务都包含验证命令和提交命令。
EOF; __tr_native_ec=$?; pwd -P >| '/var/folders/08/0c44f7c50yj6rt_5bdy80c5h0000gn/T/agent-toolhost/jobs/job-ba9b3ba966cf4af88da7b8ff7af44595/cwd.txt'; exit "$__tr_native_ec"