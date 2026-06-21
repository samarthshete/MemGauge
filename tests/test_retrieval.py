"""Unit tests for hybrid retrieval scoring."""

from uuid import uuid4

from app.memory.retrieval import cosine_similarity_01, keyword_score, rank_memories


def test_cosine_similarity_is_bounded_to_zero_one_range() -> None:
    assert cosine_similarity_01([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity_01([1.0, 0.0], [-1.0, 0.0]) == 0.0
    assert cosine_similarity_01([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_keyword_score_counts_query_token_overlap() -> None:
    assert keyword_score("likes jasmine tea", "Ari likes jasmine tea") == 1.0
    assert keyword_score("likes jasmine tea", "Ari likes coffee") == 1 / 3
    assert keyword_score("", "anything") == 0.0


def test_rank_memories_combines_vector_keyword_and_graph_signals() -> None:
    graph_id = uuid4()
    plain_id = uuid4()
    candidates = [
        {
            "id": plain_id,
            "content": "Beta likes coffee",
            "embedding": [1.0, 0.0],
        },
        {
            "id": graph_id,
            "content": "Alpha likes jasmine tea",
            "embedding": [1.0, 0.0],
        },
    ]

    ranked = rank_memories(
        query="Alpha likes jasmine",
        query_embedding=[1.0, 0.0],
        candidates=candidates,
        graph_memory_ids={graph_id},
        top_k=1,
    )

    assert ranked[0]["id"] == graph_id
    assert ranked[0]["signals"] == {"vector": 1.0, "keyword": 1.0, "graph": 1.0}
    assert ranked[0]["score"] == 1.0
