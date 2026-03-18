set shell := ["powershell", "-NoLogo", "-Command"]

compose_file := "backend/docker-compose.yml"
env_file := "backend/.env"

default:
    just --list

env:
    if (!(Test-Path {{env_file}})) { Copy-Item "backend/.env.example" {{env_file}} }

up: env
    docker compose -f {{compose_file}} --env-file {{env_file}} up -d --build

down:
    docker compose -f {{compose_file}} --env-file {{env_file}} down

restart: down up

logs:
    docker compose -f {{compose_file}} --env-file {{env_file}} logs -f --tail=200

ps:
    docker compose -f {{compose_file}} --env-file {{env_file}} ps

rebuild:
    docker compose -f {{compose_file}} --env-file {{env_file}} up -d --build --force-recreate

compose-config: env
    docker compose -f {{compose_file}} --env-file {{env_file}} config

lint:
    ruff check backend

format:
    ruff format backend
