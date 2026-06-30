"""Slug picking and the reserved-slug guard.

A spawned agent's slug becomes its ``dispatch_to_<slug>`` tool name, so it must
be unique, URL/identifier-safe, and must never collide with a reserved
specialist or an existing registered tool. We check at the slug-picking step —
before any LLM tokens burn — so the user gets a clean error early. The DB-style
uniqueness on ``spawned_agents.slug`` is the backstop, not the front line.
"""

from __future__ import annotations

import re

# Jarvis has no specialist sub-agents yet, so the reserved set is the host
# itself and the Factory. Extend this as named specialists are added.
RESERVED_SLUGS = frozenset({"jarvis", "factory"})


class SlugError(ValueError):
    """The requested name can't become a usable, non-colliding slug."""


def slugify(name_hint: str) -> str:
    slug = (name_hint or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug


def dispatch_tool_name(slug: str) -> str:
    return f"dispatch_to_{slug}"


def pick_slug(
    name_hint: str,
    *,
    taken_slugs: set[str],
    tool_names: set[str],
) -> str:
    """Validate and return a slug, or raise ``SlugError``.

    ``taken_slugs`` are slugs already used by spawned agents; ``tool_names`` is
    the live tool registry, so we refuse a slug whose dispatch tool would shadow
    an existing tool.
    """
    slug = slugify(name_hint)
    if not slug:
        raise SlugError(f"can't derive a slug from {name_hint!r}")
    if len(slug) > 40:
        raise SlugError(f"slug too long (max 40 chars): {slug!r}")
    if slug in RESERVED_SLUGS:
        raise SlugError(f"slug {slug!r} is reserved")
    if slug in taken_slugs:
        raise SlugError(f"slug {slug!r} already belongs to another agent")
    if dispatch_tool_name(slug) in tool_names:
        raise SlugError(f"slug {slug!r} would collide with an existing tool")
    return slug
