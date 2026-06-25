.PHONY: help install run dev test kafka-up kafka-down docker-up docker-down clean

help:
	@echo "Sentinel — make targets:"
	@echo "  install     create venv and install dev dependencies"
	@echo "  run         run the API + dashboard (in-memory bus, no broker needed)"
	@echo "  test        run the test suite"
	@echo "  docker-up   run the full Kafka pipeline (producer + broker + API)"
	@echo "  docker-down stop the Kafka pipeline"
	@echo "  clean       remove caches and the virtualenv"

install:
	python -m venv .venv
	.venv/Scripts/python -m pip install -U pip -r requirements-dev.txt || \
	.venv/bin/python -m pip install -U pip -r requirements-dev.txt

run:
	uvicorn app.main:app --reload --port 8100

test:
	pytest

docker-up:
	docker compose up --build

docker-down:
	docker compose down -v

clean:
	rm -rf .venv .pytest_cache **/__pycache__ .coverage
