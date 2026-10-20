"""Video indiriciler: gerçek (yt-dlp) ve sahte (demo/test için)."""
from __future__ import annotations

import hashlib
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol

log = logging.getLogger("kepce.downloader")

VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".m4v"}
ProgressFn = Callable[[float], None]

# Kullanıcıya gösterilen hata mesajları.
MSG_LOGIN = "Instagram bu isteği şimdilik engelledi. Birkaç dakika sonra tekrar dene."
MSG_PRIVATE = "Bu hesap gizli. Gizli hesapların videoları indirilemiyor."
MSG_GONE = "Gönderi bulunamadı. Silinmiş olabilir ya da link eksik kopyalanmış."
MSG_NO_VIDEO = "Bu gönderide video yok, yalnızca fotoğraf var."
MSG_TOO_BIG = "Video {mb} MB sınırından büyük."
MSG_TIMEOUT = "Instagram zamanında cevap vermedi. Tekrar dene."
MSG_GENERIC = "Video indirilemedi. Linki kontrol edip tekrar dene."


class DownloadError(Exception):
    """Mesajı doğrudan kullanıcıya gösterilebilir."""


@dataclass
class Result:
    owner: Optional[str]
    files: list[Path]


class Downloader(Protocol):
    def download(self, url: str, dest: Path, on_progress: ProgressFn) -> Result: ...


def friendly_error(text: str, max_mb: int) -> str:
    """yt-dlp'nin İngilizce hata metnini anlaşılır bir Türkçe mesaja çevirir."""
    t = (text or "").lower()
    if "private" in t:
        return MSG_PRIVATE
    if "no video" in t:
        return MSG_NO_VIDEO
    if "max-filesize" in t or "larger than max" in t:
        return MSG_TOO_BIG.format(mb=max_mb)
    if any(k in t for k in ("login", "log in", "rate-limit", "rate limit", "cookies", "401", "429", "checkpoint")):
        return MSG_LOGIN
    if any(k in t for k in ("not found", "404", "not available", "unavailable", "deleted", "does not exist")):
        return MSG_GONE
    if "timed out" in t or "timeout" in t:
        return MSG_TIMEOUT
    return MSG_GENERIC


def collect_videos(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS)


class _CaptureLogger:
    """yt-dlp mesajlarını toplar; dosya çıkmazsa nedenini anlamak için."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug] "):
            self.lines.append(msg)

    def info(self, msg: str) -> None:
        self.lines.append(msg)

    def warning(self, msg: str) -> None:
        self.lines.append(msg)

    def error(self, msg: str) -> None:
        self.lines.append(msg)


class YtDlpDownloader:
    def __init__(self, cookies_file: Optional[str], max_mb: int) -> None:
        self.cookies_file = cookies_file
        self.max_mb = max_mb

    def download(self, url: str, dest: Path, on_progress: ProgressFn) -> Result:
        import yt_dlp  # sunucuda kurulu; demo modunda gerekmez

        capture = _CaptureLogger()

        def hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    on_progress((d.get("downloaded_bytes") or 0) / total)

        opts = {
            "outtmpl": str(dest / "%(playlist_index|0)s_%(id)s.%(ext)s"),
            "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
            "merge_output_format": "mp4",
            "noplaylist": False,
            "restrictfilenames": True,
            "max_filesize": self.max_mb * 1024 * 1024,
            "socket_timeout": 20,
            "retries": 3,
            "fragment_retries": 3,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": capture,
            "progress_hooks": [hook],
        }
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True) or {}
        except yt_dlp.utils.DownloadError as exc:
            log.warning("yt-dlp hatası %s: %s", url, exc)
            raise DownloadError(friendly_error(str(exc), self.max_mb)) from None

        files = collect_videos(dest)
        if not files:
            detail = "\n".join(capture.lines)
            log.warning("Dosya çıkmadı %s: %s", url, detail[-500:])
            raise DownloadError(friendly_error(detail, self.max_mb))

        owner = info.get("uploader") or info.get("channel")
        if not owner and info.get("entries"):
            first = next((e for e in info["entries"] if e), {})
            owner = first.get("uploader") or first.get("channel")
        return Result(owner=owner, files=files)


class FakeDownloader:
    """Instagram'a hiç bağlanmadan sahte video üretir. Demo ve test içindir.

    Koddaki kelimeye göre davranır: "gizli" → gizli hesap, "silindi" → bulunamadı,
    "foto" → video yok, "coklu" → iki videolu gönderi.
    """

    def __init__(self, speed: float = 1.0) -> None:
        self.speed = speed

    def download(self, url: str, dest: Path, on_progress: ProgressFn) -> Result:
        code = url.rstrip("/").rsplit("/", 1)[-1]
        low = code.lower()
        failure = None
        if "gizli" in low:
            failure = MSG_PRIVATE
        elif "silindi" in low:
            failure = MSG_GONE
        elif "foto" in low:
            failure = MSG_NO_VIDEO

        steps = 10
        for i in range(1, steps + 1):
            time.sleep(0.25 * self.speed)
            on_progress(i / steps)
            if failure and i == 3:
                raise DownloadError(failure)

        count = 2 if "coklu" in low else 1
        files = [_fake_video(dest / f"{n}_{code}.mp4", f"{code}{n}") for n in range(1, count + 1)]
        return Result(owner="demo_hesap", files=files)


def _fake_video(path: Path, seed: str) -> Path:
    hue = int(hashlib.sha1(seed.encode()).hexdigest()[:4], 16) % 360
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc2=s=360x640:d=2:r=24,hue=h={hue}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return path
