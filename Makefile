# Raccourcis pour l'environnement local Fiduce.
# (Ces cibles servent au développement de l'app, pas à l'industrialisation.)

COMPOSE ?= docker compose

.PHONY: help up down logs ps build restart seed smoke clean

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Démarre toute la plateforme (build au besoin)
	$(COMPOSE) up -d --build
	@echo "Frontend : http://localhost:8080  |  Jaeger : http://localhost:16686  |  Prometheus : http://localhost:9090"

down: ## Arrête et supprime les conteneurs
	$(COMPOSE) down

clean: ## Arrête tout et supprime les volumes (RAZ de la base)
	$(COMPOSE) down -v

logs: ## Suit les logs (make logs SVC=ledger pour cibler un service)
	$(COMPOSE) logs -f $(SVC)

ps: ## Liste l'état des services
	$(COMPOSE) ps

build: ## Construit les images
	$(COMPOSE) build

restart: ## Redémarre un service (make restart SVC=worker)
	$(COMPOSE) restart $(SVC)

seed: ## (Ré)applique le schéma + données de référence
	$(COMPOSE) exec -T postgres psql -U fiduce -d fiduce < db/init.sql

smoke: ## Vérifie l'import/montage de chaque service (sans dépendances)
	@python3 -m venv .venv 2>/dev/null || true
	@. .venv/bin/activate && pip install -q -r services/gateway/requirements.txt \
		-r services/auth/requirements.txt -r services/ledger/requirements.txt \
		-r services/reporting/requirements.txt -r services/worker/requirements.txt && \
		PYTHONPATH=libs:services python -c "import auth.app, ledger.app, reporting.app, gateway.app, worker.worker; print('smoke OK')"
