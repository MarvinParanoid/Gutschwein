import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import notify
from app.config import settings
from app.i18n import MESSAGES, Message, language_for, t
from app.maintenance import maintenance_loop
from app.migrations import upgrade_database
from app.routers import auth, barcodes, images, uploads, users, vouchers

logging.basicConfig(level=logging.INFO, format="%(levelname)-5.5s [%(name)s] %(message)s")
log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
# Paths the SPA handles itself; "login" is where the bot's link lands and
# "demo" is the shareable link into the made-up dataset.
CLIENT_ROUTES = {"", "index.html", "login", "demo"}


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


def _reader_language(request: Request) -> str:
    return language_for(request.headers.get("accept-language"), settings.default_language)


# Errors are raised with a message key rather than a sentence, so nothing below
# has to know who is reading. The language is applied once, here at the edge.
@app.exception_handler(HTTPException)
async def localized_http_exception(request: Request, exc: HTTPException) -> Response:
    if isinstance(exc.detail, Message):
        detail = exc.detail.render(_reader_language(request))
        exc = HTTPException(exc.status_code, detail, headers=exc.headers)
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def localized_validation_error(
    request: Request, exc: RequestValidationError
) -> Response:
    """Pydantic prefixes its own text; the key is what the validator raised."""
    language = _reader_language(request)
    errors = []
    for error in exc.errors():
        key = str(error.get("msg", "")).removeprefix("Value error, ")
        errors.append({**error, "msg": t(key, language)} if key in MESSAGES else error)
    return JSONResponse(
        jsonable_encoder({"detail": errors}),
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


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
