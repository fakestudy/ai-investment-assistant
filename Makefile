.PHONY: proto test-go test-agent compose-up compose-down migrate

proto:
	buf generate

test-go:
	cd backend && go test ./...

test-agent:
	cd services/agent && python -m pytest -q

compose-up:
	docker compose --env-file .env.example -f infra/docker-compose.yml up --build

compose-down:
	docker compose --env-file .env.example -f infra/docker-compose.yml down -v

migrate:
	psql "$$DATABASE_URL" -f db/migrations/0001_init.sql
