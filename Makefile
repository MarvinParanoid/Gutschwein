.PHONY: install dev-api dev-web build test lint migration deploy deploy-vps demo-gif stats

# Machine-specific settings live outside the repository. Copy the three lines
# below into .make.local (gitignored) with your own values.
-include .make.local
VPS ?= root@gutschwein.example.com
REMOTE ?= /root/gutschwein
URL ?= https://gutschwein.example.com
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
	cd frontend && npm run test:unit

lint:
	cd backend && .venv/bin/ruff check app tests
	cd frontend && npm run typecheck

# Pins for the image build. A throwaway venv, because a freeze of the development
# one would pin pytest and ruff into production.
lock:
	rm -rf /tmp/gutschwein-lock
	python -m venv /tmp/gutschwein-lock
	/tmp/gutschwein-lock/bin/pip install -q --upgrade pip
	/tmp/gutschwein-lock/bin/pip install -q ./backend
	# The blank line after the comment block is the boundary: everything above it
	# is prose to keep, everything below is regenerated.
	@sed -n '1,/^$$/p' backend/constraints.txt > /tmp/gutschwein-lock/next
	@/tmp/gutschwein-lock/bin/pip freeze --exclude-editable \
		| grep -v '^gutschwein-backend' | sort >> /tmp/gutschwein-lock/next
	@mv /tmp/gutschwein-lock/next backend/constraints.txt
	# setuptools builds in-tree, and its leftovers are not part of the checkout.
	@rm -rf /tmp/gutschwein-lock backend/build backend/*.egg-info
	@echo "backend/constraints.txt regenerated — read the diff before committing"

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

# Visitor counts from the reverse proxy log on the VPS. Needs deploy/demo-stats
# installed there once; see docs/deploy.md.
# make stats SINCE="3 days ago"
SINCE ?= today
stats:
	@ssh $(VPS) 'demo-stats "$(SINCE)"'

# Re-records the walkthrough GIFs from the demo dataset. Needs ffmpeg.
# One language: make demo-gif LANGS=de
LANGS ?= en de
GIF_FILTER := fps=10,scale=300:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=96[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3

demo-gif:
	cd frontend && npm run build
	@for lang in $(LANGS); do \
		out=docs/demo.gif; [ "$$lang" = en ] || out=docs/demo-$$lang.gif; \
		echo "recording $$lang → $$out"; \
		(cd frontend && RECORD=1 RECORD_LANG=$$lang npx playwright test e2e/record.spec.ts) || exit 1; \
		ffmpeg -y -loglevel error -i frontend/test-results/record-walkthrough/video.webm \
			-vf "$(GIF_FILTER)" -loop 0 $$out || exit 1; \
		rm -rf frontend/test-results; \
	done
