"""Import checks for scaffold modules."""

from importlib import import_module

MODULES = [
    "app",
    "app.main",
    "app.config",
    "app.deps",
    "app.security",
    "app.observability",
    "app.db",
    "app.db.session",
    "app.db.models",
    "app.graph",
    "app.graph.neo4j_client",
    "app.graph.queries",
    "app.memory",
    "app.memory.base",
    "app.memory.mock_backend",
    "app.memory.mem0_backend",
    "app.memory.embeddings",
    "app.memory.retrieval",
    "app.routers",
    "app.routers.memories",
    "app.routers.eval",
    "app.routers.health",
    "app.eval",
    "app.eval.runner",
    "app.eval.scoring",
    "app.eval.classifier",
    "app.eval.report",
    "scripts.seed_demo",
    "scripts.run_eval_ci",
    "scripts.check_persistence",
]


def test_scaffold_modules_import() -> None:
    for module in MODULES:
        import_module(module)
