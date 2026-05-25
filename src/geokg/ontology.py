"""Ontology configuration for downstream extraction."""

ALLOWED_ENTITY_TYPES = (
    "NationState",
    "NonStateActor",
    "PoliticalLeader",
    "StrategicLocation",
    "MilitaryAsset",
)

ALLOWED_RELATION_TYPES = (
    "ATTACKED",
    "THREATENED",
    "NEGOTIATED_WITH",
    "SUPPORTED",
    "SANCTIONED",
    "BLOCKADED",
)

ALLOWED_EVENT_TYPES = (
    "AttackEvent",
    "ThreatEvent",
    "NegotiationEvent",
    "SupportEvent",
    "SanctionEvent",
    "BlockadeEvent",
)

ALLOWED_EVENT_DATE_PRECISIONS = (
    "day",
    "month",
    "year",
    "article_date",
    "unknown",
)

ALLOWED_EVENT_PARTICIPANT_ROLES = (
    "initiator",
    "target",
    "mediator",
    "supporter",
    "sanctioning_actor",
    "affected_location",
    "military_asset",
    "participant",
)

EVENT_TYPE_TO_RELATION_TYPE = {
    "AttackEvent": "ATTACKED",
    "ThreatEvent": "THREATENED",
    "NegotiationEvent": "NEGOTIATED_WITH",
    "SupportEvent": "SUPPORTED",
    "SanctionEvent": "SANCTIONED",
    "BlockadeEvent": "BLOCKADED",
}
