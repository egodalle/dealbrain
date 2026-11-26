.PHONY: up down lint test deploy deploy-status

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
	uv run pytest tests/unit/ -q

deploy:
	@bash infra/deploy.sh

deploy-status:
	ssh $(DEALBRAIN_USER)@$(DEALBRAIN_HOST) "cd /srv/dealbrain && docker compose ps"
