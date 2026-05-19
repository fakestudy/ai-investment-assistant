BUF ?= buf
GO ?= go
PNPM ?= pnpm
PYTHON ?= python3
PROTO_FILES := proto/investment/v1/agent.proto
TOOLS_BIN := $(CURDIR)/.tools/bin
CACHE_DIR := $(CURDIR)/.cache

export PATH := $(TOOLS_BIN):$(PATH)
export GOCACHE ?= $(CACHE_DIR)/go-build
export GOMODCACHE ?= $(CACHE_DIR)/go-mod

.PHONY: proto proto-tools test-go test-agent test-backend test-fronted check-chat-slice compose-up compose-down migrate

proto:
	$(BUF) generate
	$(PYTHON) -m grpc_tools.protoc -I proto --python_out=agent/app/gen --grpc_python_out=agent/app/gen $(PROTO_FILES)

proto-tools:
	mkdir -p $(TOOLS_BIN)
	GOBIN=$(TOOLS_BIN) $(GO) install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.11
	GOBIN=$(TOOLS_BIN) $(GO) install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.6.2

test-go:
	mkdir -p $(GOCACHE) $(GOMODCACHE)
	cd backend && $(GO) test ./...

test-agent:
	cd agent && $(PYTHON) -m pytest -q

test-backend:
	mkdir -p $(GOCACHE) $(GOMODCACHE)
	cd backend && $(GO) test ./...

test-fronted:
	cd fronted && $(PNPM) check

check-chat-slice: proto test-agent test-backend test-fronted

compose-up:
	docker compose --env-file .env.example -f infra/docker-compose.yml up --build

compose-down:
	docker compose --env-file .env.example -f infra/docker-compose.yml down -v

migrate:
	psql "$$DATABASE_URL" -f backend/db/migrations/0001_init.sql
