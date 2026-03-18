set shell := ["powershell", "-NoLogo", "-Command"]

compose_file := "backend/docker-compose.yml"
env_file := "backend/.env"
docker_compose := "docker-compose"
python_cmd := "\"$env:LOCALAPPDATA\\Programs\\Python\\Python311\\python.exe\""

default:
    just --list

env:
    if (!(Test-Path {{env_file}})) { Copy-Item "backend/.env.example" {{env_file}} }

up: env
    {{docker_compose}} -f {{compose_file}} --env-file {{env_file}} up -d --build

down:
    {{docker_compose}} -f {{compose_file}} --env-file {{env_file}} down

restart: down up

logs:
    {{docker_compose}} -f {{compose_file}} --env-file {{env_file}} logs -f --tail=200

ps:
    {{docker_compose}} -f {{compose_file}} --env-file {{env_file}} ps

rebuild:
    {{docker_compose}} -f {{compose_file}} --env-file {{env_file}} up -d --build --force-recreate

compose-config: env
    {{docker_compose}} -f {{compose_file}} --env-file {{env_file}} config

lint:
    ruff check backend

format:
    ruff format backend

install-dev:
    {{python_cmd}} -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt

hooks-install:
    {{python_cmd}} -m pre_commit install
    {{python_cmd}} -m pre_commit install --hook-type commit-msg

check:
    {{python_cmd}} -m pre_commit run --all-files

release-tag tag:
    git tag -a {{tag}} -m "Release {{tag}}"
