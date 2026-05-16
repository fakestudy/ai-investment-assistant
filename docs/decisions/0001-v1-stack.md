# 决策 0001：v1 技术栈

v1 使用 Next.js App Router 构建 Web 工作台，Go 构建 BFF 和内部 gRPC 服务，Python 构建 LangGraph Agent Service，PostgreSQL 做持久化，Docker Compose 做本地部署。

选择 Next.js 的原因是：它提供稳定的 App Router、成熟的生产构建和 Docker standalone 输出；产品仍然统一由 Go BFF 提供业务 API，Next.js 不承载后端业务逻辑。Go 服务共享 `backend` 下的一个 module，以复用生成的 protobuf 代码和平台工具。Python Agent Service 独立出来，因为 LangGraph 和 LangChain 以 Python 生态为主。

第一个行情 provider 是 `mock`，用于确定性开发和测试。第一个真实 adapter 是 `alpha_vantage`；provider 特有 payload 留在 `marketdata` adapter 内部，所有 UI 都展示数据来源和延迟数据标记。

Redis 不进入第一条可运行链路。PostgreSQL 存储持久数据、重试状态、通知和聊天历史。
