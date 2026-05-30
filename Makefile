SHELL := /bin/bash

.PHONY: help check-dev test-dev-config dev-start dev-end

help:
	@echo "可用命令:"
	@echo "  make check-dev   检测当前宿主机是否满足项目启动条件"
	@echo "  make test-dev-config  测试本地开发脚本配置解析"
	@echo "  make dev-start   启动本地开发环境 (postgres + backend + web)"
	@echo "  make dev-end     停止本地开发环境"

check-dev:
	@bash scripts/check-dev.sh

test-dev-config:
	@bash scripts/test-dev-config.sh

dev-start:
	@bash scripts/dev-start.sh

dev-end:
	@bash scripts/dev-end.sh
