SHELL := /bin/bash

.PHONY: help install agent-claude-dev check-dev test-dev-config dev-start dev-stop chat-cli

help:
	@echo "可用命令:"
	@echo "  make install          安装 web / agent_claude 依赖"
	@echo "  make agent-claude-dev 启动 agent_claude 开发服务"
	@echo "  make check-dev        检测当前宿主机是否满足项目启动条件"
	@echo "  make test-dev-config  测试本地开发脚本配置解析"
	@echo "  make dev-start        启动本地开发环境 (postgres + nginx + pgweb + agent_claude api + web)"
	@echo "  make dev-stop         停止本地开发环境"
	@echo "  make chat-cli         启动终端版聊天 CLI (需先 make dev-start)"

install:
	cd web && pnpm install
	cd agent_claude && uv sync

agent-claude-dev:
	cd agent_claude && PYTHONPYCACHEPREFIX=../.pycache uv run python main.py

check-dev:
	@bash scripts/check-dev.sh

test-dev-config:
	@bash scripts/test-dev-config.sh

dev-start:
	@bash scripts/dev-start.sh

dev-stop:
	@bash scripts/dev-stop.sh

chat-cli:
	cd web && pnpm chat:cli
