import base64
from html import escape
from urllib.parse import urlparse

import requests
import streamlit as st


_SILHOUETTE = """
<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 96 96" role="img" aria-label="Player silhouette">
  <rect width="96" height="96" rx="48" fill="#e8edf3"/>
  <circle cx="48" cy="34" r="17" fill="#9aa8b7"/>
  <path d="M16 88c2-20 14-31 32-31s30 11 32 31" fill="#9aa8b7"/>
</svg>
""".strip()


_ALLOWED_IMAGE_HOSTS = {"static.lolesports.com", "static.wikia.nocookie.net"}


def _detect_image_content_type(content: bytes) -> str:
    """Identify common raster image formats when a CDN returns a generic MIME type."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return ""


@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_image_data_url(image_url: str) -> str:
    """Fetch trusted image hosts server-side to avoid browser hotlink failures."""
    url = str(image_url or "").strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in _ALLOWED_IMAGE_HOSTS:
        return ""
    if parsed.scheme == "http":
        url = parsed._replace(scheme="https").geturl()

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "FantasyLCS/1.0 (player portrait display)",
                "Referer": "https://lol.fandom.com/",
            },
            timeout=8,
        )
        response.raise_for_status()
    except requests.RequestException:
        return ""

    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type in {"application/octet-stream", "binary/octet-stream", "application/binary"}:
        content_type = _detect_image_content_type(response.content)
    if not content_type.startswith("image/") or content_type == "image/svg+xml":
        return ""
    if len(response.content) > 5_000_000:
        return ""
    encoded = base64.b64encode(response.content).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def render_player_image(image_url: str | None, size: int = 80) -> None:
    """Render a cached portrait or a silhouette when its image cannot be loaded."""
    url = str(image_url or "").strip()
    image_src = _fetch_image_data_url(url) if url else ""
    style = f"width:{int(size)}px;height:{int(size)}px;"
    if image_src:
        content = (
            f'<div style="{style}position:relative;">'
            f'<img src="{escape(image_src, quote=True)}" alt="Player portrait" '
            f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'block\';" '
            f'style="{style}object-fit:cover;border-radius:50%;background:#e8edf3;" />'
            f'<div style="{style}display:none;position:absolute;inset:0;">{_SILHOUETTE}</div>'
            '</div>'
        )
    else:
        content = f'<div style="{style}">{_SILHOUETTE}</div>'
    st.markdown(content, unsafe_allow_html=True)


def render_org_logo(image_url: str | None, size: int = 80) -> None:
    """Render a cached organization logo in a square frame."""
    url = str(image_url or "").strip()
    image_src = _fetch_image_data_url(url) if url else ""
    style = f"width:{int(size)}px;height:{int(size)}px;"
    if image_src:
        content = (
            f'<img src="{escape(image_src, quote=True)}" alt="League organization logo" '
            f'style="{style}object-fit:contain;border-radius:10px;background:#fff;" />'
        )
    else:
        content = (
            f'<div aria-label="Organization logo unavailable" style="{style}display:flex;'
            'align-items:center;justify-content:center;border-radius:10px;'
            'background:#e8edf3;color:#667788;font-weight:700;">ORG</div>'
        )
    st.markdown(content, unsafe_allow_html=True)
