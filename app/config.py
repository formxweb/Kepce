"""Ayarlar ortam değişkenlerinden okunur; hepsinin makul bir varsayılanı var."""
from __future__ import annotations

import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

# Bir istekte en fazla kaç link işlenir.
MAX_LINKS = 20
# Aynı anda en fazla kaç video indirilir (tüm kullanıcılar toplamı).
MAX_CONCURRENT = _int("MAX_CONCURRENT", 4)
# İndirilen dosyalar kaç dakika sonra silinir.
JOB_TTL_MINUTES = _int("JOB_TTL_MINUTES", 30)
# Bir IP adresi saatte en fazla kaç liste başlatabilir.
JOBS_PER_HOUR = _int("JOBS_PER_HOUR", 15)
# Tek video için boyut sınırı (MB).
MAX_FILESIZE_MB = _int("MAX_FILESIZE_MB", 300)
# Başarısız bir link en fazla kaç kez yeniden denenebilir.
MAX_ATTEMPTS = _int("MAX_ATTEMPTS", 3)

DATA_DIR = Path(os.getenv("DATA_DIR", "/tmp/kepce-data"))
# Instagram giriş isterse: Netscape biçiminde cookies.txt dosyasının yolu.
COOKIES_FILE = os.getenv("IG_COOKIES_FILE") or None
# "ytdlp" (gerçek) ya da "fake" (Instagram'a gitmeden demo/test).
DOWNLOADER = os.getenv("DOWNLOADER", "ytdlp").strip().lower()
# Render/Railway gibi bir proxy arkasındaysan 1 yap; gerçek IP X-Forwarded-For'dan okunur.
TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"
