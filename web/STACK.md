# 前端技术栈（web/STACK.md）

> 本文件由一次完整的 grill-me 决策树拷问沉淀而来，与 [`docs/project/PLAN.md`](../docs/project/PLAN.md) 共同作为前端实现的"决策锁定文件"。
> 12 周内若想换库、换栈、换框架，先来这里查一遍——决策已锁，不再讨论。

---

## 0. 适用范围

- 仅描述 **`web/` 子项目**（Next.js 前端）的技术选型与落地约束。
- 后端、Agent、proto、docker-compose 等不在本文件范围内，当前/目标架构详见 [`ARCHITECTURE.md`](../docs/project/ARCHITECTURE.md)。

---

## 1. 决策摘要（已锁，不再讨论）

| # | 决策项 | 结论 |
|---|--------|------|
| 1 | 路由模式 | **Next.js App Router**（RSC + streaming） |
| 2 | 语言 | **TypeScript** |
| 3 | 包管理器 | **pnpm** |
| 4 | Lint / Format | **Biome**（需对齐 shadcn 风格） |
| 5 | 样式 | **Tailwind CSS** |
| 6 | UI 组件 | **shadcn/ui**（CLI 复制源码到本地） |
| 7 | 图标 | **lucide-react** |
| 8 | Toast | **sonner** |
| 9 | 动画 | **framer-motion** |
| 10 | 服务端状态 | **TanStack Query** |
| 11 | 全局状态 | **Zustand** |
| 12 | 表单 | **react-hook-form + zod** |
| 13 | 高级表格 | **@tanstack/react-table** |
| 14 | 日期 | **date-fns** |
| 15 | AI 数据层 | **自定义 chat API + JSON SSE + Zustand store** |
| 16 | AI 对话组件 | **AI Elements**（Vercel 官方，shadcn 模式分发） |
| 17 | 流式协议 | **项目自定义 JSON SSE**（当前由 `agent_claude` 输出，未来 Go BFF 接管时保持兼容或显式迁移） |
| 18 | 通用 Markdown | **react-markdown + remark-gfm + rehype-highlight + remark-math + rehype-katex** |
| 19 | 股价图表 | **lightweight-charts**（TradingView 官方） |
| 20 | 财务/KPI 图表 | **Recharts** |
| 21 | 测试 | **v0.x 不写**（与 AI 全包前端策略匹配） |
| 22 | AI 协作强度 | **整体 C 档（AI 全包）**——这是对 PLAN 第 9.1 节的局部变更，需在 PLAN 第 14 节登记 |

---

## 2. 分层全景

```
┌─────────────────────────────────────────────────────────────┐
│  框架层  Next.js (App Router) + TypeScript + pnpm + Biome    │
├─────────────────────────────────────────────────────────────┤
│  UI 层   Tailwind + shadcn/ui + lucide-react + sonner        │
│          + framer-motion                                     │
├─────────────────────────────────────────────────────────────┤
│  数据层  TanStack Query + Zustand + react-hook-form + zod    │
│          + @tanstack/react-table + date-fns                  │
├─────────────────────────────────────────────────────────────┤
│  AI 层   AI Elements UI + 自定义 JSON SSE chat store           │
│          + react-markdown 全家桶（非对话场景）                 │
├─────────────────────────────────────────────────────────────┤
│  图表层  lightweight-charts（K 线）+ Recharts（财务/KPI）     │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 页面与库的对应关系

### 3.1 AI 对话页（`/chat`）

| 需求 | 选型 |
|------|------|
| 消息列表 / 气泡 / 滚动 | AI Elements `<Conversation>` `<Message>` |
| 输入框（自动增高、Enter 发送、停止按钮） | AI Elements `<PromptInput>` |
| 流式 Markdown 渲染 | AI Elements `<Response>` |
| 工具调用展示 | AI Elements `<Tool>` |
| 思维链折叠 | AI Elements `<Reasoning>` |
| 引用来源（财报片段） | AI Elements `<Sources>` |
| 建议提问（空状态） | AI Elements `<Suggestion>` |
| 会话状态机 | `features/chat/store.ts` 中的 Zustand store |
| 后端流式协议 | 项目自定义 JSON SSE：`message_created` / `reasoning` / `delta` / `tool_call` / `tool_result` / `title` / `done` / `error` |

### 3.2 股票分析页（`/stocks/[symbol]`）

| 需求 | 选型 |
|------|------|
| 股价 K 线 / 折线 / 面积图 | lightweight-charts |
| 营收 / 利润 / 现金流柱图 | Recharts |
| 业务结构饼图 / 同比环比 | Recharts |
| KPI 指标卡 | shadcn/ui `<Card>` 自拼 |
| AI 分析报告（长 Markdown） | react-markdown + remark/rehype 插件 |
| 公告 / 新闻列表（可排序、可筛选） | @tanstack/react-table |
| 股价轮询 / 新闻拉取 | TanStack Query |

---

## 4. 接入步骤（落地顺序）

> 让 AI 严格按以下顺序生成代码，避免步骤错乱。

1. **初始化 Next.js**
   ```bash
   pnpm create next-app@latest web --typescript --app --tailwind --eslint=false --src-dir=false --import-alias="@/*"
   cd web
   ```

2. **替换 ESLint 为 Biome**
   ```bash
   pnpm add -D --save-exact @biomejs/biome
   pnpm biome init
   ```
   修改 `biome.json`：
   ```json
   {
     "javascript": {
       "formatter": {
         "quoteStyle": "double",
         "semicolons": "always"
       }
     }
   }
   ```

3. **初始化 shadcn/ui**
   ```bash
   pnpm dlx shadcn@latest init
   pnpm dlx shadcn@latest add button card dialog input textarea form table sheet scroll-area
   ```

4. **安装 AI Elements 相关依赖**
   ```bash
   pnpm add ai @ai-sdk/react
   pnpm dlx ai-elements@latest
   ```

   当前聊天数据层不使用 `useChat` 作为状态机，也不要求后端输出 AI SDK Data Stream Protocol。

5. **安装数据 / 状态 / 表单层**
   ```bash
   pnpm add @tanstack/react-query @tanstack/react-table zustand
   pnpm add react-hook-form zod @hookform/resolvers
   pnpm add date-fns
   ```

6. **安装 UI 辅助**
   ```bash
   pnpm add lucide-react sonner framer-motion
   ```

7. **安装图表**
   ```bash
   pnpm add lightweight-charts recharts
   ```

8. **安装 Markdown 全家桶**
   ```bash
   pnpm add react-markdown remark-gfm rehype-highlight remark-math rehype-katex
   pnpm add -D @types/react-syntax-highlighter
   ```

---

## 5. 关键约束（容易踩坑，必读）

1. **shadcn/ui 不是 npm 包**——它是 CLI 生成器，组件源码会复制到 `components/ui/`，可任意修改。AI 写脚手架时常误以为是 `import` 来的库，需在 prompt 里特别说明。

2. **AI Elements 同样是 shadcn 模式分发**——组件落到 `components/ai-elements/`，与 `components/ui/` 并列。

3. **当前流式协议是项目自定义 JSON SSE**——每个 SSE `data:` 里是一条 `ChatStreamEvent` JSON。当前输出方是 `agent_claude`；未来 Go BFF 接管 `/api/*` 后，要么保持该事件契约，要么先做一次明确的前后端协议迁移，不要静默切到 AI SDK Data Stream Protocol。

4. **Biome 默认风格与 shadcn 不一致**——必须设 `quoteStyle: "double"`、`semicolons: "always"`，否则首次 `format` 会触发成片变更，污染 git diff。

5. **App Router 的 'use client' 边界**——AI 写组件时常忘加。规则：用了 `useState` / `useEffect` / 浏览器 API / 第三方 client 组件（如 lightweight-charts、Recharts、framer-motion）的文件，顶部必须 `'use client'`。

6. **lightweight-charts 不是 React 组件**——它是 imperative API，需要 `useRef` + `useEffect` 包装。AI 自己拼时容易忘记清理函数，导致路由切换后内存泄漏。

7. **AI Elements 中文资料几乎为零**——遇到问题去英文 issue / 源码找答案，不要靠搜索引擎。

---

## 6. 目录结构（参考）

```
web/
├── app/
│   ├── layout.tsx
│   ├── page.tsx                    # 首页
│   ├── chat/
│   │   └── page.tsx                # AI 对话页
│   ├── stocks/
│   │   └── [symbol]/
│   │       └── page.tsx            # 股票分析页
│   └── api/
│       └── ...                     # 默认不写业务 API route
├── components/
│   ├── ui/                         # shadcn/ui 生成
│   ├── ai-elements/                # AI Elements 生成
│   ├── chat/                       # 业务对话组件
│   └── stocks/                     # 股票分析业务组件
├── lib/
│   ├── api.ts                      # 调 /api 的 fetch/SSE 封装
│   ├── query-client.ts             # TanStack Query
│   └── store/                      # Zustand store
├── biome.json
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

注意：当前所有 API 走 `/api/*`，经 Nginx 代理到 `agent_claude`。未来 Go BFF 接管后，前端仍优先保持 `/api/*` 调用路径不变。**不要在 `web/app/api/` 下补业务后端逻辑**；真正后端能力应放在当前 `agent_claude` 或未来 Go BFF。

---

## 7. 决策变更记录

> 任何前端选型变更必须在此处登记，并同步登记到 PLAN 第 14 节。

| 日期 | 项目 | 原决策 | 新决策 | 原因 |
|------|------|--------|--------|------|
| - | - | - | - | - |

---

## 8. 与 PLAN.md 的关联

- 本文件等于 PLAN 第 2 节"技术栈"的前端展开版，并以 ARCHITECTURE 当前/目标链路为边界。
- PLAN 第 9.1 节将 Next.js 页面骨架划入 C 档；本文件将**整个前端**划入 C 档（AI 全包），属于对 PLAN 的局部变更，需在 PLAN 第 14 节同步登记。
- 第 4 周末出 demo 的硬节点（PLAN 第 5 节）由本文件的栈兜底实现。
