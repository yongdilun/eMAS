from __future__ import annotations

from typing import Any

from .v2_contracts import HydratedToolCard


def identity_arg_names(requirement: Any) -> set[str]:
    entity = str(getattr(requirement, "entity", "") or "").strip()
    names = {"id", "entity_id", "record_id"}
    if entity:
        names.update({f"{entity}_id", f"{entity}_ref"})
    return names


def card_entity_matches_requirement(card: HydratedToolCard, requirement: Any) -> bool:
    entity = str(getattr(requirement, "entity", "") or "").strip().lower()
    if not entity:
        return True
    endpoint_root = str(card.metadata.get("endpoint_root") or "").strip().lower()
    return endpoint_root == entity


def card_supports_collection_read(card: HydratedToolCard) -> bool:
    if card.path_params:
        return False
    if "{id}" in card.tool_name or "id" in set(card.required_args):
        return False
    if "list" in set(card.actions):
        return True
    return bool(card.supports_filters or card.supports_sort or card.supports_limit)


def card_supports_single_entity_read(card: HydratedToolCard, requirement: Any) -> bool:
    if requirement is None:
        return False
    if not bool(card.is_read_only) or bool(card.requires_approval):
        return False
    if not card_entity_matches_requirement(card, requirement):
        return False
    if not {"read_one", "read"}.intersection(set(card.actions)):
        return False
    identity_args = set(card.path_params or []) | set(card.required_args or [])
    if identity_args.intersection(identity_arg_names(requirement)):
        return True
    endpoint_shape = str(card.metadata.get("endpoint_shape") or "").strip().lower()
    return endpoint_shape == "item" and not card_supports_collection_read(card)
