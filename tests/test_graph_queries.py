"""Integration tests for Neo4j graph query helpers."""

import pytest

pytestmark = pytest.mark.integration


async def test_multi_hop_related_entities_and_collision_query(clean_stores: None) -> None:
    from app.config import get_settings
    from app.graph.neo4j_client import Neo4jClient

    graph = Neo4jClient(settings=get_settings())
    try:
        await graph.run_write(
            """
            CREATE (alice:Entity {name: 'PhaseEightAlice'})
            CREATE (bob:Entity {name: 'PhaseEightBob'})
            CREATE (carol:Entity {name: 'PhaseEightCarol'})
            CREATE (acmeSpaced:Entity {name: 'Acme Inc'})
            CREATE (acmeCompact:Entity {name: 'AcmeInc'})
            CREATE (alice)-[:RELATES_TO {predicate: 'knows'}]->(bob)
            CREATE (bob)-[:RELATES_TO {predicate: 'mentors'}]->(carol)
            """,
            {},
        )

        related = await graph.related_entities("PhaseEightAlice", hops=2)
        assert {item["name"] for item in related} >= {"PhaseEightBob", "PhaseEightCarol"}
        assert {item["predicate"] for item in related} >= {"knows", "mentors"}

        collisions = await graph.entity_resolution_collisions(threshold=0)
        assert {
            (frozenset({item["left_name"], item["right_name"]}), item["distance"])
            for item in collisions
        } >= {(frozenset({"Acme Inc", "AcmeInc"}), 0)}
    finally:
        await graph.close()
