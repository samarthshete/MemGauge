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


async def test_active_facts_returns_non_null_memory_id(clean_stores: None) -> None:
    """Regression for BUG-1: ACTIVE_FACTS must surface the real `memory_id`.

    The query previously read `rel.source_memory_id` (never written), so every
    `active_facts()` row came back with `memory_id = None`. Seeding a fact through
    the real write path (which sets `rel.memory_id`) must yield a non-null
    `memory_id` equal to the stored memory's id.
    """

    from app.config import get_settings
    from app.db.session import AsyncSessionLocal
    from app.graph.neo4j_client import Neo4jClient
    from app.memory.embeddings import get_embedding_provider
    from app.memory.mock_backend import MockMemoryBackend

    settings = get_settings()
    graph = Neo4jClient(settings=settings)
    try:
        async with AsyncSessionLocal() as session:
            backend = MockMemoryBackend(
                session=session,
                graph=graph,
                embeddings=get_embedding_provider(),
            )
            add_result = await backend.add(
                text="PhaseEightDana likes oolong tea.",
                user_id="phase8-active-facts",
            )

        assert add_result["stored"] is True
        stored_memory_id = add_result["memory"]["id"]

        facts = await graph.active_facts("PhaseEightDana")

        # The fact exists and is active.
        assert facts, "expected at least one active fact for the seeded entity"
        fact = next(f for f in facts if f["target"] == "oolong tea")

        # The bug fix: memory_id is present, non-null, and the actual stored id.
        assert "memory_id" in fact
        assert fact["memory_id"] is not None
        assert fact["memory_id"] == stored_memory_id

        # Guard against the old wrong field leaking back into the public result.
        assert "source_memory_id" not in fact
    finally:
        await graph.close()
