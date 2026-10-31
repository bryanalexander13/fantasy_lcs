"""Player portrait lookup using Leaguepedia's MediaWiki API."""

from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
import re
import unicodedata

import requests
import streamlit as st


API_URL = "https://lol.fandom.com/api.php"
TEAM_CODES = {
    "team liquid": "TL",
    "team liquid honda": "TL",
    "team liquid alienware": "TL",
    "cloud9": "C9",
    "cloud9 kia": "C9",
    "flyquest": "FLY",
    "lyon": "LYON",
    "sentinels": "SEN",
    "dignitas": "DIG",
    "shopify rebellion": "SR",
    "disguised": "DSG",
}
KNOWN_PLAYER_FILE_HINTS = {
    ("yeon", "tl"): "TL Yeon 2025 Split 1.png",
    ("saint", "lyon"): "LYON Saint 2025 Split 1.png",
}
HEADERS = {
    "User-Agent": "FantasyLCS/1.0 (player portrait lookup)",
    "Referer": "https://lol.fandom.com/",
}


def _normalized_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = value.replace("_", " ").strip().casefold()
    return re.sub(r"\s+", " ", value)


def _team_values(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item or "").strip()]
    value = str(value or "").strip()
    return [value] if value else []


def _matches_team(actual: str, expected) -> bool:
    actual_norm = _normalized_title(actual)
    return any(
        actual_norm and expected_norm and (
            actual_norm == expected_norm or (
                min(len(actual_norm), len(expected_norm)) >= 4
                and (actual_norm in expected_norm or expected_norm in actual_norm)
            )
        )
        for expected_norm in (_normalized_title(value) for value in _team_values(expected))
    )


def _quoted(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _cargo_rows(table: str, fields: str, where: str) -> list[dict]:
    try:
        response = requests.get(
            API_URL,
            params={
                "action": "cargoquery",
                "format": "json",
                "tables": table,
                "fields": fields,
                "where": where,
                "limit": 500,
            },
            headers=HEADERS,
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return []
    return [row.get("title", {}) for row in payload.get("cargoquery", [])]


def _file_thumbnail_urls(file_names: list[str]) -> dict[str, str]:
    names = list(dict.fromkeys(str(name or "").strip() for name in file_names if str(name or "").strip()))
    urls = {}
    for start in range(0, len(names), 50):
        chunk = names[start:start + 50]
        titles = "|".join(
            name if name.casefold().startswith("file:") else f"File:{name}"
            for name in chunk
        )
        try:
            response = requests.get(
                API_URL,
                params={
                    "action": "query",
                    "format": "json",
                    "formatversion": 2,
                    "titles": titles,
                    "prop": "imageinfo",
                    "iiprop": "url",
                    "iiurlwidth": 256,
                },
                headers=HEADERS,
                timeout=8,
            )
            response.raise_for_status()
            pages = response.json().get("query", {}).get("pages", [])
        except (requests.RequestException, ValueError):
            continue
        if isinstance(pages, dict):
            pages = list(pages.values())
        for page in pages:
            image_info = page.get("imageinfo") or []
            if not image_info:
                continue
            title = str(page.get("title", ""))
            normalized = _normalized_title(title.removeprefix("File:"))
            thumbnail = str(image_info[0].get("thumburl") or image_info[0].get("url") or "").strip()
            if normalized and thumbnail:
                urls[normalized] = thumbnail
    return urls


@lru_cache(maxsize=1)
def _player_image_category_files() -> tuple[str, ...]:
    """Load Leaguepedia's indexed player-photo file titles once per process."""
    file_names = []
    continuation = {}
    while True:
        params = {
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "list": "categorymembers",
            "cmtitle": "Category:Player Images",
            "cmtype": "file",
            "cmlimit": 500,
        }
        params.update(continuation)
        try:
            response = requests.get(API_URL, params=params, headers=HEADERS, timeout=8)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            break
        for item in payload.get("query", {}).get("categorymembers", []):
            title = str(item.get("title", "")).strip()
            if title:
                file_names.append(title.removeprefix("File:"))
        continuation = payload.get("continue", {})
        if not continuation:
            break
    return tuple(dict.fromkeys(file_names))


def _team_search_terms(team_context) -> list[str]:
    terms = []
    for team in _team_values(team_context):
        code = TEAM_CODES.get(_normalized_title(team))
        for term in (team, code):
            if term and _normalized_title(term) not in {_normalized_title(existing) for existing in terms}:
                terms.append(term)
    return terms


def _contains_title_phrase(title: str, phrase: str) -> bool:
    normalized_title = f" {_normalized_title(title)} "
    normalized_phrase = f" {_normalized_title(phrase)} "
    return normalized_phrase.strip() in normalized_title


def _search_player_files(player_name: str, team_context) -> list[str]:
    """Find image files whose titles contain both the player and their org."""
    files = []
    normalized_player = _normalized_title(player_name)
    for team_term in _team_search_terms(team_context):
        try:
            response = requests.get(
                API_URL,
                params={
                    "action": "query",
                    "format": "json",
                    "formatversion": 2,
                    "list": "search",
                    "srnamespace": 6,
                    "srsearch": f'intitle:"{team_term} {player_name}"',
                    "srlimit": 20,
                },
                headers=HEADERS,
                timeout=5,
            )
            response.raise_for_status()
            results = response.json().get("query", {}).get("search", [])
        except (requests.RequestException, ValueError):
            continue
        for result in results:
            title = str(result.get("title", ""))
            file_title = title.removeprefix("File:")
            normalized = _normalized_title(file_title)
            if not _contains_title_phrase(normalized, normalized_player) or not _contains_title_phrase(
                normalized, team_term
            ):
                continue
            files.append(file_title)
    files = list(dict.fromkeys(files))
    files.sort(
        key=lambda value: max((int(year) for year in re.findall(r"20\d{2}", value)), default=0),
        reverse=True,
    )
    return files


def _category_player_files(player_name: str, team_context) -> list[str]:
    if not _team_values(team_context):
        return []
    normalized_player = _normalized_title(player_name)
    team_terms = _team_search_terms(team_context)
    hints = [
        KNOWN_PLAYER_FILE_HINTS[(normalized_player, _normalized_title(team_term))]
        for team_term in team_terms
        if (normalized_player, _normalized_title(team_term)) in KNOWN_PLAYER_FILE_HINTS
    ]
    if hints:
        return hints
    files = [
        file_name for file_name in _player_image_category_files()
        if _contains_title_phrase(file_name, normalized_player)
        and any(
            _contains_title_phrase(file_name, team_term)
            for team_term in team_terms
        )
    ]
    files.sort(
        key=lambda value: max((int(year) for year in re.findall(r"20\d{2}", value)), default=0),
        reverse=True,
    )
    return files


def _cargo_player_images(
    player_names: list[str], team_by_player: dict[str, object] | None = None,
) -> dict[str, str]:
    names = list(dict.fromkeys(str(name or "").strip() for name in player_names if str(name or "").strip()))
    if not names:
        return {}

    team_by_player = team_by_player or {}
    candidates: dict[str, list[tuple[int, int, str, str]]] = {name: [] for name in names}

    def add_image_rows(query_names: list[str], name_to_owner: dict[str, str]) -> None:
        if not query_names:
            return
        conditions = []
        for query_name in query_names:
            conditions.append(f"Link={_quoted(query_name)}")
        image_rows = _cargo_rows(
            "PlayerImages",
            "Link,FileName,IsProfileImage,Team",
            " OR ".join(conditions),
        )
        for row in image_rows:
            row_names = [row.get("Link", "")]
            matched_names = {
                name_to_owner[_normalized_title(row_name)]
                for row_name in row_names
                if _normalized_title(row_name) in name_to_owner
            }
            file_name = str(row.get("FileName", "")).strip()
            if not file_name:
                continue
            profile_value = str(row.get("IsProfileImage", "")).strip().casefold()
            is_profile = profile_value in {"1", "true", "yes", "y"}
            for name in matched_names:
                team_match = int(_matches_team(row.get("Team", ""), team_by_player.get(name, [])))
                candidates[name].append((int(is_profile), team_match, "", file_name))

        player_where = " OR ".join(f"Player={_quoted(name)}" for name in query_names)
        player_rows = _cargo_rows("Players", "Player,Image,Team", player_where)
        for row in player_rows:
            name = name_to_owner.get(_normalized_title(row.get("Player", "")))
            file_name = str(row.get("Image", "")).strip()
            if name and file_name:
                team_match = int(_matches_team(row.get("Team", ""), team_by_player.get(name, [])))
                candidates[name].append((3, team_match, "", file_name))

        # As a second exact source, query the profile table by current org. Its
        # page title may be disambiguated (for example, "Yeon (Sean Sung)").
        teams = []
        for query_name in query_names:
            owner = name_to_owner.get(_normalized_title(query_name))
            owner_teams = _team_values(team_by_player.get(owner, [])) if owner else []
            for team in owner_teams:
                if team not in teams:
                    teams.append(team)
        if teams:
            team_where = " OR ".join(
                condition
                for team in teams
                for condition in (f"Team={_quoted(team)}", f"Team LIKE {_quoted('%' + team + '%')}")
            )
            team_rows = _cargo_rows("Players", "Player,Image,Team", team_where)
            for row in team_rows:
                page_title = str(row.get("Player", ""))
                page_base = page_title.split("(", 1)[0]
                file_name = str(row.get("Image", "")).strip()
                if not file_name:
                    continue
                for name in names:
                    if _normalized_title(page_title) != _normalized_title(name) and (
                        _normalized_title(page_base) != _normalized_title(name)
                    ):
                        continue
                    team_match = int(_matches_team(row.get("Team", ""), team_by_player.get(name, [])))
                    if team_match:
                        candidates[name].append((4, team_match, "", file_name))

    name_to_owner = {_normalized_title(name): name for name in names}
    add_image_rows(names, name_to_owner)

    # LoL Esports handles are sometimes aliases of the page's current title.
    # Leaguepedia's redirect table maps alternate spellings to that page name.
    unresolved = [
        name for name in names
        if not candidates[name] or (
            _team_values(team_by_player.get(name, []))
            and not any(candidate[1] for candidate in candidates[name])
        )
    ]
    if unresolved:
        redirect_where = " OR ".join(
            condition
            for name in unresolved
            for condition in (
                f"AllName={_quoted(name)}",
                f"OverviewPage={_quoted(name)}",
                f"AllName LIKE {_quoted('%' + name + '%')}",
            )
        )
        redirects = _cargo_rows("PlayerRedirects", "AllName,OverviewPage", redirect_where)
        canonical_to_owner = {}
        redirect_names = []
        for row in redirects:
            canonical = str(row.get("OverviewPage", "")).strip()
            aliases = re.split(r"[,|]", str(row.get("AllName", "")))
            for name in unresolved:
                if any(_normalized_title(alias) == _normalized_title(name) for alias in aliases) or (
                    _normalized_title(canonical) == _normalized_title(name)
                ):
                    if canonical:
                        canonical_to_owner[_normalized_title(canonical)] = name
                    for alias in aliases:
                        alias = alias.strip()
                        if alias:
                            canonical_to_owner[_normalized_title(alias)] = name
                            redirect_names.append(alias)
        canonical_to_owner.update(name_to_owner)
        canonical_names = list(dict.fromkeys(
            str(row.get("OverviewPage", "")).strip()
            for row in redirects if str(row.get("OverviewPage", "")).strip()
        ))
        redirect_names = list(dict.fromkeys(canonical_names + redirect_names))
        if redirect_names:
            add_image_rows(redirect_names, canonical_to_owner)

    selected_files = {}
    for name, rows in candidates.items():
        if rows:
            # Prefer the player infobox image, then explicitly marked profile
            # photos, then the newest image tagged to that player.
            rows.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
            selected_files[name] = rows[0][3]

    file_urls = _file_thumbnail_urls(list(selected_files.values()))
    results = {}
    for name, file_name in selected_files.items():
        normalized_file = _normalized_title(file_name.removeprefix("File:"))
        if normalized_file in file_urls:
            results[name] = file_urls[normalized_file]
    return results


@lru_cache(maxsize=1024)
def find_player_image(player_name: str) -> str:
    """Return a Fandom thumbnail only when its page title clearly matches the player."""
    name = str(player_name or "").strip()
    if not name:
        return ""

    try:
        response = requests.get(
            API_URL,
            params={
                "action": "query",
                "format": "json",
                "formatversion": 2,
                "generator": "search",
                "gsrsearch": f'intitle:"{name}"',
                "gsrnamespace": 0,
                "gsrlimit": 10,
                "prop": "pageimages|categories",
                "piprop": "thumbnail",
                "pithumbsize": 256,
                "cllimit": 50,
            },
            headers=HEADERS,
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return ""

    pages = payload.get("query", {}).get("pages", [])
    if isinstance(pages, dict):
        pages = list(pages.values())

    wanted = _normalized_title(name)
    matches = []
    for page in pages:
        title = str(page.get("title", "")).strip()
        normalized = _normalized_title(title)
        title_base = _normalized_title(title.split("(", 1)[0])
        if normalized != wanted and title_base != wanted:
            continue
        categories = [
            str(category.get("title", "")).casefold()
            for category in (page.get("categories") or [])
        ]
        if any("disambiguation" in category for category in categories):
            continue
        image_url = str((page.get("thumbnail") or {}).get("source", "")).strip()
        if image_url:
            # Prefer an exact page title over a profile title with the player's
            # real name in parentheses (for example, "Handle (Real Name)").
            matches.append((normalized != wanted, image_url))

    if not matches:
        return ""
    matches.sort(key=lambda match: match[0])
    return matches[0][1]


@st.cache_data(ttl=86400, show_spinner=False, max_entries=256)
def find_player_images(
    player_names: list[str], team_by_player: dict[str, object] | None = None,
) -> dict[str, str]:
    """Resolve player-linked images first, then fall back to page thumbnails."""
    names = list(dict.fromkeys(str(name or "").strip() for name in player_names if str(name or "").strip()))
    if not names:
        return {}

    found = _cargo_player_images(names, team_by_player)
    unresolved_names = [name for name in names if name not in found]
    for start in range(0, len(unresolved_names), 50):
        chunk = unresolved_names[start:start + 50]
        try:
            response = requests.get(
                API_URL,
                params={
                    "action": "query",
                    "format": "json",
                    "formatversion": 2,
                    "titles": "|".join(chunk),
                    "prop": "pageimages|categories",
                    "piprop": "thumbnail",
                    "pithumbsize": 256,
                    "cllimit": 50,
                },
                headers=HEADERS,
                timeout=8,
            )
            response.raise_for_status()
            pages = response.json().get("query", {}).get("pages", [])
        except (requests.RequestException, ValueError):
            return found
        if isinstance(pages, dict):
            pages = list(pages.values())
        by_title = {_normalized_title(page.get("title", "")): page for page in pages}
        for name in chunk:
            page = by_title.get(_normalized_title(name))
            if page:
                categories = [
                    str(category.get("title", "")).casefold()
                    for category in (page.get("categories") or [])
                ]
                if any("disambiguation" in category for category in categories):
                    continue
                image_url = str((page.get("thumbnail") or {}).get("source", "")).strip()
                if image_url:
                    found[name] = image_url

    unresolved = [name for name in names if name not in found]
    if unresolved:
        file_candidates = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            for name, files in zip(
                unresolved,
                executor.map(
                    lambda player: _category_player_files(
                        player, (team_by_player or {}).get(player, [])
                    ) or _search_player_files(
                        player, (team_by_player or {}).get(player, [])
                    ),
                    unresolved,
                ),
            ):
                if files:
                    file_candidates[name] = files[0]
        file_urls = _file_thumbnail_urls(list(file_candidates.values()))
        for name, file_name in file_candidates.items():
            image_url = file_urls.get(_normalized_title(file_name))
            if image_url:
                found[name] = image_url

    unresolved = [name for name in names if name not in found]
    if unresolved:
        # A few wiki pages include the player's real name in parentheses, so
        # search only unresolved aliases and keep the exact-title safety check.
        with ThreadPoolExecutor(max_workers=3) as executor:
            for name, image_url in zip(unresolved, executor.map(find_player_image, unresolved)):
                if image_url:
                    found[name] = image_url
    return found
