BUF ?= buf
GO ?= go
PYTHON ?= python3
PROTO_FILES := proto/investment/v1/agent.proto
TOOLS_BIN := $(CURDIR)/.tools/bin

export PATH := $(TOOLS_BIN):$(PATH)

.PHONY: proto proto-tools test-go test-agent compose-up compose-down migrate

proto:
	$(BUF) generate
	$(PYTHON) -m grpc_tools.protoc -I proto --python_out=agent/app/gen --grpc_python_out=agent/app/gen $(PROTO_FILES)

proto-tools:
	mkdir -p $(TOOLS_BIN)
	GOBIN=$(TOOLS_BIN) $(GO) install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.11
	GOBIN=$(TOOLS_BIN) $(GO) install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.6.2

test-go:
	cd backend && go test ./...

test-agent:
	cd agent && python -m pytest -q

compose-up:
	docker compose --env-file .env.example -f infra/docker-compose.yml up --build

compose-down:
	docker compose --env-file .env.example -f infra/docker-compose.yml down -v

migrate:
	psql "$$DATABASE_URL" -f backend/db/migrations/0001_init.sql
