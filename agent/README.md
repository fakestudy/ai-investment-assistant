## 本地运行

API: uv run python main.py

Worker: uv run python -m worker.main

Outbox publisher: uv run python -m worker.outbox_publisher

RabbitMQ management: http://localhost:15672

PostgreSQL 是业务状态真相；RabbitMQ 消息可能重复，不能用队列长度推断审批状态。
