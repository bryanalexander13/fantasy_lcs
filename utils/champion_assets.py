"""Resolve LoL champion identifiers to Riot Data Dragon icons."""

import re

import requests
import streamlit as st


DATA_DRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
DATA_DRAGON_CDN = "https://ddragon.leagueoflegends.com/cdn"


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


@st.cache_data(ttl=86400, show_spinner=False)
def _champion_catalog() -> tuple[str, dict]:
    versions_response = requests.get(DATA_DRAGON_VERSIONS_URL, timeout=10)
    versions_response.raise_for_status()
    versions = versions_response.json()
    if not versions:
        raise ValueError("Riot Data Dragon did not return a game version.")
    version = str(versions[0])
    catalog_response = requests.get(
        f"{DATA_DRAGON_CDN}/{version}/data/en_US/champion.json", timeout=10
    )
    catalog_response.raise_for_status()
    catalog = catalog_response.json().get("data") or {}
    return version, catalog


def champion_asset(identifier: str | None) -> dict:
    """Return canonical champion name and icon URL when Data Dragon is reachable."""
    raw = str(identifier or "").strip()
    if not raw:
        return {"name": "", "icon_url": ""}
    try:
        version, catalog = _champion_catalog()
    except (requests.RequestException, ValueError, TypeError):
        return {"name": raw, "icon_url": ""}

    target = _normalize(raw)
    for key, champion in catalog.items():
        if target in {
            _normalize(key), _normalize(champion.get("id")),
            _normalize(champion.get("key")), _normalize(champion.get("name")),
        }:
            filename = (champion.get("image") or {}).get("full") or f"{key}.png"
            return {
                "name": str(champion.get("name") or raw),
                "icon_url": f"{DATA_DRAGON_CDN}/{version}/img/champion/{filename}",
            }
    return {"name": raw, "icon_url": ""}


def champion_names() -> list[str]:
    """Return the canonical current champion names from Riot Data Dragon."""
    try:
        _, catalog = _champion_catalog()
    except (requests.RequestException, ValueError, TypeError):
        return []
    return sorted(
        {str(champion.get("name") or "").strip() for champion in catalog.values() if champion.get("name")},
        key=str.casefold,
    )
