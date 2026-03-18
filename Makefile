COMPOSE_FILE=backend/docker-compose.yml
ENV_FILE=backend/.env
DOCKER_COMPOSE?=docker-compose

.PHONY: help env up down restart logs ps rebuild lint format compose-config install-dev hooks-install check release-tag

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
	@echo "  install-dev    - install dev dependencies"
	@echo "  hooks-install  - install pre-commit hooks"
	@echo "  check          - run pre-commit checks on all files"
	@echo "  release-tag    - create local release tag (usage: make release-tag TAG=v0.1.0)"

env:
	@if [ ! -f $(ENV_FILE) ]; then cp backend/.env.example $(ENV_FILE); fi

up: env
	$(DOCKER_COMPOSE) -f $(COMPOSE_FILE) --env-file $(ENV_FILE) up -d --build

down:
	$(DOCKER_COMPOSE) -f $(COMPOSE_FILE) --env-file $(ENV_FILE) down

restart: down up

logs:
	$(DOCKER_COMPOSE) -f $(COMPOSE_FILE) --env-file $(ENV_FILE) logs -f --tail=200

ps:
	$(DOCKER_COMPOSE) -f $(COMPOSE_FILE) --env-file $(ENV_FILE) ps

rebuild:
	$(DOCKER_COMPOSE) -f $(COMPOSE_FILE) --env-file $(ENV_FILE) up -d --build --force-recreate

compose-config:
	$(DOCKER_COMPOSE) -f $(COMPOSE_FILE) --env-file $(ENV_FILE) config

lint:
	ruff check backend

format:
	ruff format backend

install-dev:
	python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt

hooks-install:
	python -m pre_commit install
	python -m pre_commit install --hook-type commit-msg

check:
	python -m pre_commit run --all-files

release-tag:
	@test -n "$(TAG)" || (echo "TAG is required, e.g. TAG=v0.1.0" && exit 1)
	git tag -a $(TAG) -m "Release $(TAG)"
