# AI 投资助手前端

`fronted` 是 AI 投资助手的 Web 工作台项目，使用 Next.js App Router、React、TypeScript、Tailwind CSS 和 TanStack Query。

## 本地开发

安装依赖：

```bash
pnpm install
```

启动开发服务：

```bash
pnpm dev
```

默认访问地址是 `http://localhost:3000`。

## 环境变量

复制 `.env.local.example` 为 `.env.local`：

```bash
cp .env.local.example .env.local
```

`NEXT_PUBLIC_API_BASE_URL` 指向 Go BFF，例如本地默认 `http://localhost:8080`。

## 验证

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

或一次性运行：

```bash
pnpm check
```
