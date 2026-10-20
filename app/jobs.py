"""İndirme listeleri (job), kuyruk, küçük resim ve temizlik."""
from __future__ import annotations

import asyncio
import logging
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .downloader import MSG_GENERIC, Downloader, DownloadError, Result
from .links import Link

log = logging.getLogger("kepce.jobs")

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "error"
MARKER = ".kepce-job"


@dataclass
class OutFile:
    name: str
    path: Path
    size: int
    thumb: Optional[Path] = None


@dataclass
class Item:
    id: str
    link: Link
    status: str = QUEUED
    progress: float = 0.0
    error: Optional[str] = None
    owner: Optional[str] = None
    attempts: int = 0
    files: list[OutFile] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.status in (DONE, FAILED)


@dataclass
class Job:
    id: str
    dir: Path
    items: list[Item]
    created: float = field(default_factory=time.time)

    @property
    def finished(self) -> bool:
        return all(i.finished for i in self.items)

    def item(self, item_id: str) -> Optional[Item]:
        return next((i for i in self.items if i.id == item_id), None)


def make_thumb(video: Path) -> Optional[Path]:
    """Videonun ilk karelerinden küçük bir JPG üretir; olmazsa None."""
    thumb = video.with_suffix(".jpg")
    for seek in ("0.4", "0"):
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", seek, "-i", str(video),
                 "-frames:v", "1", "-vf", "scale=240:-2", str(thumb)],
                check=True, capture_output=True, timeout=30,
            )
        except (subprocess.SubprocessError, OSError):
            continue
        if thumb.exists() and thumb.stat().st_size > 0:
            return thumb
    return None


class JobStore:
    def __init__(self, downloader: Downloader, data_dir: Path, max_concurrent: int,
                 ttl_seconds: int, max_attempts: int) -> None:
        self.downloader = downloader
        self.data_dir = data_dir
        self.ttl = ttl_seconds
        self.max_attempts = max_attempts
        self.jobs: dict[str, Job] = {}
        self._sem = asyncio.Semaphore(max_concurrent)
        self._tasks: set[asyncio.Task] = set()

    # --- yaşam döngüsü -------------------------------------------------
    def wipe_leftovers(self) -> None:
        """Önceki çalışmadan kalan liste klasörlerini siler (yalnızca bizim işaretlediklerimizi)."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for child in self.data_dir.iterdir():
            if child.is_dir() and (child / MARKER).exists():
                shutil.rmtree(child, ignore_errors=True)

    def create(self, links: list[Link]) -> Job:
        job_id = secrets.token_urlsafe(12)
        job_dir = self.data_dir / job_id
        job_dir.mkdir(parents=True)
        (job_dir / MARKER).touch()
        items = [Item(id=str(n), link=link) for n, link in enumerate(links, start=1)]
        job = Job(id=job_id, dir=job_dir, items=items)
        self.jobs[job_id] = job
        for item in items:
            self._spawn(job, item)
        return job

    def retry(self, job: Job, item: Item) -> bool:
        if item.status != FAILED or item.attempts >= self.max_attempts:
            return False
        item.status, item.progress, item.error = QUEUED, 0.0, None
        self._spawn(job, item)
        return True

    def cleanup(self, now: Optional[float] = None) -> int:
        """Süresi dolan listeleri ve dosyalarını siler."""
        now = now or time.time()
        expired = [
            j for j in self.jobs.values()
            if (j.finished and now - j.created > self.ttl) or now - j.created > self.ttl * 3
        ]
        for job in expired:
            self.jobs.pop(job.id, None)
            shutil.rmtree(job.dir, ignore_errors=True)
        return len(expired)

    # --- indirme -------------------------------------------------------
    def _spawn(self, job: Job, item: Item) -> None:
        task = asyncio.create_task(self._run(job, item))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, job: Job, item: Item) -> None:
        async with self._sem:
            if job.id not in self.jobs:
                return
            item.attempts += 1
            item.status = RUNNING
            item_dir = job.dir / item.id
            shutil.rmtree(item_dir, ignore_errors=True)
            item_dir.mkdir(parents=True)

            def on_progress(fraction: float) -> None:
                # İlerleme hiç geri gitmesin; %100'ü dosya hazır olunca göster.
                item.progress = max(item.progress, min(max(fraction, 0.0), 1.0) * 0.95)

            try:
                result = await asyncio.to_thread(
                    self.downloader.download, item.link.url, item_dir, on_progress)
                files = await asyncio.to_thread(self._finalize, item, result)
            except DownloadError as exc:
                item.status, item.error = FAILED, str(exc)
                return
            except Exception:
                log.exception("Beklenmeyen hata: %s", item.link.url)
                item.status, item.error = FAILED, MSG_GENERIC
                return

            item.owner = result.owner
            item.files = files
            item.progress = 1.0
            item.status = DONE

    @staticmethod
    def _finalize(item: Item, result: Result) -> list[OutFile]:
        out: list[OutFile] = []
        many = len(result.files) > 1
        for n, src in enumerate(result.files, start=1):
            name = f"instagram_{item.link.code}{f'_{n}' if many else ''}{src.suffix.lower()}"
            dst = src.with_name(name)
            if src != dst:
                src.replace(dst)
            out.append(OutFile(name=name, path=dst, size=dst.stat().st_size, thumb=make_thumb(dst)))
        if not out:
            raise DownloadError(MSG_GENERIC)
        return out


def job_public(job: Job, store: JobStore) -> dict:
    base = f"/api/jobs/{job.id}/items"
    max_attempts = store.max_attempts
    return {
        "id": job.id,
        "finished": job.finished,
        "expires_in": max(0, int(store.ttl - (time.time() - job.created))),
        "items": [
            {
                "id": it.id,
                "kind": it.link.kind,
                "code": it.link.code,
                "url": it.link.url,
                "status": it.status,
                "progress": round(it.progress * 100),
                "error": it.error,
                "owner": it.owner,
                "can_retry": it.status == FAILED and it.attempts < max_attempts,
                "files": [
                    {
                        "name": f.name,
                        "size": f.size,
                        "url": f"{base}/{it.id}/files/{n}",
                        "thumb": f"{base}/{it.id}/thumbs/{n}" if f.thumb else None,
                    }
                    for n, f in enumerate(it.files)
                ] if it.status == DONE else [],
            }
            for it in job.items
        ],
    }
