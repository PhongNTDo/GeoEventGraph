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
