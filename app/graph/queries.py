"""Parameterized Cypher queries for MemGauge graph reads."""

RELATED_ENTITIES = """
MATCH path = (:Entity {name: $name})-[rels:RELATES_TO*1..2]-(entity:Entity)
WHERE length(path) <= $hops
UNWIND rels AS rel
RETURN DISTINCT entity.name AS name, rel.predicate AS predicate
ORDER BY name, predicate
"""

ENTITY_RESOLUTION_COLLISIONS = """
MATCH (left:Entity), (right:Entity)
WHERE elementId(left) < elementId(right)
WITH
    left,
    right,
    toLower(replace(left.name, ' ', '')) AS left_name,
    toLower(replace(right.name, ' ', '')) AS right_name
WHERE left_name = right_name OR abs(size(left_name) - size(right_name)) <= $threshold
RETURN
    left.name AS left_name,
    right.name AS right_name,
    CASE WHEN left_name = right_name THEN 0 ELSE abs(size(left_name) - size(right_name)) END
        AS distance
ORDER BY distance, left_name, right_name
"""

ACTIVE_FACTS = """
MATCH (:Entity {name: $entity})-[rel:RELATES_TO]->(target:Entity)
WHERE rel.valid_to IS NULL
RETURN
    target.name AS target,
    rel.predicate AS predicate,
    rel.valid_from AS valid_from,
    rel.source_memory_id AS memory_id
ORDER BY predicate, target
"""
