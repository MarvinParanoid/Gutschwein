.PHONY: install dev-api dev-web build test lint migration deploy deploy-vps

VPS ?= root@185.142.99.209
REMOTE ?= /root/sparschwein
URL ?= https://spar-schwein.duckdns.org
# data/ holds the database and uploads. It is excluded, and rsync never deletes
# excluded paths, so --delete cannot eat it.
# --no-owner/--no-group: rsync run as root would otherwise stamp the remote files
# with the local uid (1000), which git then rejects as "dubious ownership".
RSYNC_FLAGS := -a --no-owner --no-group
RSYNC_EXCLUDES := --exclude '.git' --exclude 'frontend/node_modules' \
	--exclude 'backend/.venv' --exclude 'backend/static' --exclude 'data' \
	--exclude '__pycache__' --exclude '.ruff_cache' --exclude '.pytest_cache' \
	--exclude '*.egg-info' --exclude '.claude'

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm install

# Local development: API on :8000, Vite on :5173 proxying /api to it.
dev-api:
	cd backend && DEV_MODE=true RUN_BOT=false .venv/bin/uvicorn app.main:app --reload

dev-web:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

test:
	cd backend && .venv/bin/python -m pytest -q

lint:
	cd backend && .venv/bin/ruff check app tests
	cd frontend && npm run typecheck

# make migration m="add reminder flag"
migration:
	cd backend && .venv/bin/alembic revision --autogenerate -m "$(m)"

deploy:
	docker compose up -d --build

# $(CURDIR)/ pins the sync root to this directory: running rsync with a relative
# './' from a subdirectory once mirrored frontend/ over the whole project.
deploy-vps:
	rsync $(RSYNC_FLAGS) --delete $(RSYNC_EXCLUDES) $(CURDIR)/ $(VPS):$(REMOTE)/
	# Every build leaves the previous image dangling, and the VPS disk is shared
	# with other services — so prune right after a successful build.
	ssh $(VPS) 'cd $(REMOTE) && docker compose up -d --build && docker image prune -f >/dev/null && docker builder prune -f >/dev/null'
	@echo "ждём готовности $(URL) ..."
	@for i in $$(seq 1 30); do \
		curl -fsS $(URL)/healthz && echo " ✓ поднялся" && exit 0; \
		sleep 2; \
	done; \
	echo "НЕ поднялся за минуту — смотрите: ssh $(VPS) 'cd $(REMOTE) && docker compose logs app'"; \
	exit 1
