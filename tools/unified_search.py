"""Build the cross-module search projection consumed by the global search UI."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


class UnifiedSearchError(ValueError):
    """Raised when a search projection would publish ambiguous records."""


def _text(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, (list, tuple)):
            parts.extend(str(item).strip() for item in value if str(item).strip())
    return " ".join(dict.fromkeys(parts))


def _index(rows: Iterable[Mapping[str, Any]], key: str = "id") -> dict[str, Mapping[str, Any]]:
    return {
        str(row[key]): row
        for row in rows
        if isinstance(row, Mapping) and row.get(key) is not None
    }


def build_unified_search_index(
    catalog: Mapping[str, Any],
    story_search_index: Mapping[str, Any] | None,
    release_id: str,
) -> dict[str, Any]:
    """Normalize searchable entities without inventing cross-resource relations."""
    bands = _index(catalog.get("bands", []))
    characters = _index(catalog.get("characters", []))
    entries: list[dict[str, Any]] = []

    for track in catalog.get("musicTracks", []):
        entries.append({
            "id": str(track.get("id", "")),
            "type": "music",
            "title": str(track.get("title") or track.get("id") or ""),
            "subtitle": _text(track.get("bandLabels", []), track.get("vocalistLabels", [])),
            "href": f"/music/{track.get('id')}/",
            "status": str(track.get("catalogStatus") or "identified"),
            "searchableText": _text(
                track.get("title"),
                track.get("phoneticTitle"),
                track.get("rubyTitle"),
                track.get("bandLabels", []),
                track.get("vocalistLabels", []),
                track.get("lyricist"),
                track.get("composer"),
                track.get("arranger"),
                track.get("id"),
            ),
        })

    for character in catalog.get("characters", []):
        band = bands.get(str(character.get("bandId", "")), {})
        entries.append({
            "id": str(character.get("id", "")),
            "type": "character",
            "title": str(character.get("displayName") or character.get("id") or ""),
            "subtitle": _text(band.get("displayName"), character.get("role")),
            "href": f"/characters/{character.get('id')}/",
            "status": str(character.get("catalogStatus") or "identified"),
            "searchableText": _text(
                character.get("displayName"),
                character.get("shortName"),
                character.get("aliases", []),
                character.get("role"),
                band.get("displayName"),
                character.get("id"),
            ),
        })

    for card in catalog.get("memberCards", []):
        character = characters.get(str(card.get("characterId", "")), {})
        band = bands.get(str(character.get("bandId", "")), {})
        entries.append({
            "id": str(card.get("id", "")),
            "type": "member_card",
            "title": str(card.get("subtitle") or card.get("displayName") or card.get("id") or ""),
            "subtitle": _text(character.get("displayName"), band.get("displayName")),
            "href": f"/cards/members/{card.get('id')}/",
            "status": str(card.get("catalogStatus") or "identified"),
            "searchableText": _text(
                card.get("displayName"),
                card.get("subtitle"),
                card.get("name"),
                character.get("displayName"),
                character.get("shortName"),
                character.get("aliases", []),
                band.get("displayName"),
                card.get("masterId"),
                card.get("id"),
            ),
        })

    for card in catalog.get("supportCards", []):
        featured = [
            characters.get(str(character_id), {})
            for character_id in card.get("featuredCharacterIds", [])
        ]
        featured_names = [item.get("displayName") for item in featured]
        featured_aliases = [
            alias
            for item in featured
            for alias in item.get("aliases", [])
        ]
        entries.append({
            "id": str(card.get("id", "")),
            "type": "support_card",
            "title": str(card.get("description") or card.get("displayName") or card.get("id") or ""),
            "subtitle": _text(featured_names),
            "href": f"/cards/supports/{card.get('id')}/",
            "status": str(card.get("catalogStatus") or "identified"),
            "searchableText": _text(
                card.get("displayName"),
                card.get("description"),
                card.get("name"),
                featured_names,
                featured_aliases,
                card.get("masterId"),
                card.get("id"),
            ),
        })

    story_entries = (
        story_search_index.get("entries", [])
        if isinstance(story_search_index, Mapping)
        else []
    )
    for story in story_entries:
        kind = str(story.get("kind") or "story")
        entries.append({
            "id": str(story.get("id", "")),
            "type": "story",
            "title": str(story.get("title") or story.get("id") or ""),
            "subtitle": _text(kind, story.get("summary")),
            "href": f"/stories/episodes/{story.get('id')}/",
            "status": str(story.get("parseStatus") or "metadata_only"),
            "searchableText": _text(
                story.get("title"),
                story.get("summary"),
                story.get("searchableText"),
                kind,
                story.get("id"),
            ),
        })

    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry["type"], entry["id"])
        if not entry["id"] or key in seen:
            raise UnifiedSearchError(
                f"duplicate search entry: {entry['type']}:{entry['id']}"
            )
        seen.add(key)

    entries.sort(key=lambda item: (item["type"], item["title"], item["id"]))
    return {
        "schemaVersion": 1,
        "sourceReleaseId": release_id,
        "entries": entries,
        "counts": {
            kind: sum(entry["type"] == kind for entry in entries)
            for kind in ("music", "character", "member_card", "support_card", "story")
        },
    }
