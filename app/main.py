"""HTTP uçları. Çalıştırma: uvicorn app.main:app"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import config
from .downloader import Downloader, FakeDownloader, YtDlpDownloader
from .jobs import FAILED, Job, JobStore, job_public
from .links import parse_links

log = logging.getLogger("kepce")
MAX_BODY = 32_000


# --- yardımcılar -------------------------------------------------------
def error(status: int, message: str, **extra) -> JSONResponse:
    headers = extra.pop("headers", None)
    return JSONResponse({"error": message, **extra}, status_code=status, headers=headers)


def client_ip(request: Request) -> str:
    if config.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # En sağdaki adresi proxy'nin kendisi ekler; soldakiler sahte olabilir.
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self.hits: dict[str, deque] = defaultdict(deque)

    def _trim(self, key: str, now: float) -> deque:
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        q = self._trim(key, now)
        if len(q) >= self.limit:
            return False, int(self.window - (now - q[0])) + 1
        q.append(now)
        return True, 0

    def prune(self) -> None:
        now = time.monotonic()
        for key in list(self.hits):
            if not self._trim(key, now):
                del self.hits[key]


class SecurityHeaders:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("X-Frame-Options", "DENY")
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _job_or_404(request: Request) -> tuple[Optional[Job], Optional[JSONResponse]]:
    job = request.app.state.store.jobs.get(request.path_params["job_id"])
    if job is None:
        return None, error(404, "Bu listenin süresi dolmuş. Linkleri yeniden yapıştır.")
    return job, None


# --- uçlar -------------------------------------------------------------
async def create_job(request: Request) -> JSONResponse:
    store: JobStore = request.app.state.store
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return error(413, "İstek çok büyük.")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return error(400, "Geçersiz istek.")
    urls = body.get("urls") if isinstance(body, dict) else None
    if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
        return error(400, "Geçersiz istek.")

    links, rejected = parse_links("\n".join(urls))
    if not links:
        return error(422, "Geçerli bir Instagram video linki bulunamadı. Reels ya da gönderi linki yapıştır.",
                     rejected=rejected[:20])
    if len(links) > config.MAX_LINKS:
        return error(422, f"Bir seferde en fazla {config.MAX_LINKS} link indirilebilir.")

    allowed, wait = request.app.state.limiter.allow(client_ip(request))
    if not allowed:
        minutes = max(1, round(wait / 60))
        return error(429, f"Çok fazla liste başlattın. {minutes} dakika sonra tekrar dene.",
                     headers={"Retry-After": str(wait)})

    job = store.create(links)
    return JSONResponse(job_public(job, store), status_code=201)


async def get_job(request: Request) -> JSONResponse:
    job, err = _job_or_404(request)
    if err:
        return err
    return JSONResponse(job_public(job, request.app.state.store), headers={"Cache-Control": "no-store"})


async def retry_item(request: Request) -> JSONResponse:
    store: JobStore = request.app.state.store
    job, err = _job_or_404(request)
    if err:
        return err
    item = job.item(request.path_params["item_id"])
    if item is None:
        return error(404, "Böyle bir video yok.")
    if item.status != FAILED:
        return error(409, "Bu video zaten indiriliyor ya da hazır.")
    if not store.retry(job, item):
        return error(409, "Bu link birkaç kez denendi ve olmadı. Linki kontrol et.")
    return JSONResponse(job_public(job, store))


def _file_for(request: Request):
    job, err = _job_or_404(request)
    if err:
        return None, err
    item = job.item(request.path_params["item_id"])
    n = request.path_params["n"]
    if item is None or item.status != "done" or not (0 <= n < len(item.files)):
        return None, error(404, "Dosya bulunamadı.")
    return item.files[n], None


async def download_file(request: Request):
    f, err = _file_for(request)
    if err:
        return err
    return FileResponse(f.path, media_type="video/mp4", filename=f.name)


async def thumb_file(request: Request):
    f, err = _file_for(request)
    if err:
        return err
    if not f.thumb:
        return error(404, "Küçük resim yok.")
    return FileResponse(f.thumb, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "downloader": request.app.state.downloader_name,
                         "jobs": len(request.app.state.store.jobs)})


# --- uygulama ----------------------------------------------------------
def make_downloader() -> tuple[Downloader, str]:
    if config.DOWNLOADER == "fake":
        return FakeDownloader(), "fake"
    return YtDlpDownloader(cookies_file=config.COOKIES_FILE, max_mb=config.MAX_FILESIZE_MB), "ytdlp"


def create_app(downloader: Optional[Downloader] = None, data_dir: Optional[Path] = None,
               ttl_seconds: Optional[int] = None, jobs_per_hour: Optional[int] = None) -> Starlette:
    if downloader is None:
        downloader, name = make_downloader()
    else:
        name = type(downloader).__name__
    store = JobStore(
        downloader=downloader,
        data_dir=data_dir or config.DATA_DIR,
        max_concurrent=config.MAX_CONCURRENT,
        ttl_seconds=ttl_seconds if ttl_seconds is not None else config.JOB_TTL_MINUTES * 60,
        max_attempts=config.MAX_ATTEMPTS,
    )
    limiter = RateLimiter(jobs_per_hour or config.JOBS_PER_HOUR, 3600)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        store.wipe_leftovers()

        async def sweep():
            while True:
                await asyncio.sleep(60)
                removed = store.cleanup()
                limiter.prune()
                if removed:
                    log.info("%d eski liste silindi", removed)

        task = asyncio.create_task(sweep())
        try:
            yield
        finally:
            task.cancel()

    routes = [
        Route("/healthz", health),
        Route("/api/jobs", create_job, methods=["POST"]),
        Route("/api/jobs/{job_id}", get_job),
        Route("/api/jobs/{job_id}/items/{item_id}/retry", retry_item, methods=["POST"]),
        Route("/api/jobs/{job_id}/items/{item_id}/files/{n:int}", download_file),
        Route("/api/jobs/{job_id}/items/{item_id}/thumbs/{n:int}", thumb_file),
        Mount("/", app=StaticFiles(directory=config.STATIC_DIR, html=True)),
    ]
    app = Starlette(routes=routes, lifespan=lifespan, middleware=[Middleware(SecurityHeaders)])
    app.state.store = store
    app.state.limiter = limiter
    app.state.downloader_name = name
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
