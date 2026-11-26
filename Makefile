.PHONY: up down lint test migrate ingest ingest-dry-run dedupe eval deploy deploy-status

DATASET ?= philly
SUITE ?= all

up:
	docker compose up -d --wait
	@docker compose ps
	@echo "Stack is healthy."

down:
	docker compose down -v

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy --strict .

test:
	docker compose up -d --wait db
	uv run pytest tests/unit/ -q $(if $(filter-out all,$(SUITE)),-k $(SUITE),)

dedupe:
	docker compose up -d --wait db
	uv run python -m pipelines.dedupe

eval:
	uv run python evals/$(SUITE)/run_eval.py

migrate:
	uv run python -m pipelines.migrate

ingest:
	docker compose up -d --wait db && uv run python -m pipelines.run --dataset $(DATASET)

ingest-dry-run:
	uv run python -m pipelines.run --dataset $(DATASET) --dry-run

deploy:
	@bash infra/deploy.sh

deploy-status:
	ssh $(DEALBRAIN_USER)@$(DEALBRAIN_HOST) "cd /srv/dealbrain && docker compose ps"
