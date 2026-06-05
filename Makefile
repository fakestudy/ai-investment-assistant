SHELL := /bin/bash

.PHONY: help install agent-dev check-dev test-dev-config dev-start dev-stop

help:
	@echo "可用命令:"
	@echo "  make install     安装 web / agent 依赖"
	@echo "  make agent-dev   启动 agent 开发服务"
	@echo "  make check-dev   检测当前宿主机是否满足项目启动条件"
	@echo "  make test-dev-config  测试本地开发脚本配置解析"
	@echo "  make dev-start   启动本地开发环境 (postgres + nginx + agent + web)"
	@echo "  make dev-stop    停止本地开发环境"

install:
	cd web && pnpm install
	cd agent && uv sync

agent-dev:
	cd agent && PYTHONPYCACHEPREFIX=../.pycache uv run python main.py

check-dev:
	@bash scripts/check-dev.sh

test-dev-config:
	@bash scripts/test-dev-config.sh

dev-start:
	@bash scripts/dev-start.sh

dev-stop:
	@bash scripts/dev-stop.sh
