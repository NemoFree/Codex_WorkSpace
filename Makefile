COMPOSE_FILE=backend/docker-compose.yml
ENV_FILE=backend/.env

.PHONY: help env up down restart logs ps rebuild lint format compose-config

help:
	@echo "Targets:"
	@echo "  env            - create backend/.env from example if missing"
	@echo "  up             - build and start all services"
	@echo "  down           - stop and remove containers"
	@echo "  restart        - restart stack"
	@echo "  logs           - tail logs"
	@echo "  ps             - show service status"
	@echo "  rebuild        - rebuild and restart"
	@echo "  compose-config - validate compose file"
	@echo "  lint           - run ruff lint"
	@echo "  format         - run ruff format"

env:
	@if [ ! -f $(ENV_FILE) ]; then cp backend/.env.example $(ENV_FILE); fi

up: env
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) up -d --build

down:
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) down

restart: down up

logs:
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) logs -f --tail=200

ps:
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) ps

rebuild:
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) up -d --build --force-recreate

compose-config:
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) config

lint:
	ruff check backend

format:
	ruff format backend
