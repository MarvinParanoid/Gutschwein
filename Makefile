.PHONY: install dev-api dev-web build test lint migration deploy demo-gif stats

# Machine-specific settings live outside the repository. Copy the line below into
# .make.local (gitignored) with your own value.
-include .make.local
VPS ?= root@gutschwein.example.com

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

# A local build, for development. Production is deployed by the Deploy workflow
# through deploy/deploy.sh on the server — never from here.
deploy:
	docker compose up -d --build

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
