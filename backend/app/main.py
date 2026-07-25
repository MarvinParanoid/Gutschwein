import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import notify
from app.config import settings
from app.maintenance import maintenance_loop
from app.migrations import upgrade_database
from app.routers import auth, barcodes, images, uploads, users, vouchers

logging.basicConfig(level=logging.INFO, format="%(levelname)-5.5s [%(name)s] %(message)s")
log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
# Paths the SPA handles itself; "login" is where the bot's link lands.
CLIENT_ROUTES = {"", "index.html", "login"}


def _report_bot_exit(task: asyncio.Task) -> None:
    """Nothing awaits the bot task, so without this a crash would be silent."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("telegram bot stopped with an error", exc_info=exc)
    else:
        log.warning("telegram bot task finished unexpectedly")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(upgrade_database)

    bot_task: asyncio.Task | None = None
    bot = None
    if settings.run_bot and settings.bot_token:
        from app.bot import create_bot, run_bot

        bot = create_bot()
        notify.set_notifier(bot)
        bot_task = asyncio.create_task(run_bot(bot))
        bot_task.add_done_callback(_report_bot_exit)
        log.info("telegram bot started")
    else:
        log.warning(
            "bot disabled: RUN_BOT=%s, token set=%s",
            settings.run_bot,
            bool(settings.bot_token),
        )

    housekeeping = asyncio.create_task(maintenance_loop())

    try:
        yield
    finally:
        notify.set_notifier(None)
        housekeeping.cancel()
        if bot_task is not None:
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass
        if bot is not None:
            await bot.session.close()


app = FastAPI(title="Sparschwein", lifespan=lifespan)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(vouchers.router)
app.include_router(uploads.router)
app.include_router(images.router)
app.include_router(barcodes.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


# The built Mini App is served by this same process; mounted last so /api wins.
if (STATIC_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        candidate = (STATIC_DIR / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(STATIC_DIR):
            return FileResponse(candidate)
        # Only known client routes fall back to index.html. Everything else is a
        # 404 rather than a cheerful 200 for every /.env a scanner asks for.
        if path in CLIENT_ROUTES:
            return FileResponse(STATIC_DIR / "index.html")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
