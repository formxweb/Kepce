"""Yapıştırılan metinden Instagram video linklerini ayıklar ve tek biçime getirir."""
from __future__ import annotations

import re
from dataclasses import dataclass

_SPLIT = re.compile(r"[\s,;]+")
# instagram.com/reel/KOD, /reels/KOD, /p/KOD, /tv/KOD ve kullanici/reel/KOD biçimleri.
_IG = re.compile(
    r"^(?:https?://)?(?:www\.|m\.)?instagram\.com/"
    r"(?:[A-Za-z0-9_.]{1,30}/)?"
    r"(p|reels?|tv)/([A-Za-z0-9_-]{5,64})(?:[/?#].*)?$",
    re.IGNORECASE,
)
_EDGE = "<>()[]\"'"
_TRAIL = ".,!?;:"


@dataclass(frozen=True)
class Link:
    kind: str  # "p" | "reel" | "tv"
    code: str

    @property
    def url(self) -> str:
        return f"https://www.instagram.com/{self.kind}/{self.code}/"


def _looks_like_url(token: str) -> bool:
    return token.lower().startswith("http") or ("." in token and "/" in token)


def parse_links(text: str) -> tuple[list[Link], list[str]]:
    """Metindeki geçerli linkleri (tekrarsız, sırayla) ve reddedilen URL'leri döndürür."""
    links: list[Link] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for raw in _SPLIT.split(text or ""):
        token = raw.strip(_EDGE).rstrip(_TRAIL).strip(_EDGE)
        if not token or not _looks_like_url(token):
            continue
        match = _IG.match(token)
        if not match:
            rejected.append(token)
            continue
        kind = match.group(1).lower()
        if kind.startswith("reel"):
            kind = "reel"
        code = match.group(2)
        if code in seen:
            continue
        seen.add(code)
        links.append(Link(kind, code))
    return links, rejected
