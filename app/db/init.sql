CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS memories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    agent_id text NULL,
    run_id text NULL,
    content text NOT NULL,
    embedding vector(384) NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    superseded_by uuid NULL REFERENCES memories(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_memories_user_id ON memories(user_id);
CREATE INDEX IF NOT EXISTS ix_memories_embedding_hnsw
    ON memories USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS ix_memories_active ON memories(is_active) WHERE is_active;

CREATE TABLE IF NOT EXISTS memory_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_id uuid NULL REFERENCES memories(id),
    event_type text NOT NULL CONSTRAINT ck_memory_events_event_type
        CHECK (event_type IN ('ADD','UPDATE','DELETE','NOOP')),
    old_content text NULL,
    new_content text NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_memory_events_memory_id ON memory_events(memory_id);
ALTER TABLE memory_events ALTER COLUMN memory_id DROP NOT NULL;

CREATE TABLE IF NOT EXISTS eval_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    dataset_name text NOT NULL,
    git_sha text NULL,
    backend_mode text NOT NULL,
    recall_at_5 double precision NOT NULL,
    precision double precision NOT NULL,
    staleness_rate double precision NOT NULL,
    false_fact_rate double precision NOT NULL,
    p95_search_ms double precision NOT NULL,
    p95_add_ms double precision NOT NULL,
    total_cases integer NOT NULL,
    passed boolean NOT NULL,
    baseline_id uuid NULL
);

CREATE TABLE IF NOT EXISTS eval_case_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES eval_runs(id),
    case_id text NOT NULL,
    failure_mode text NOT NULL CONSTRAINT ck_eval_case_results_failure_mode
        CHECK (failure_mode IN ('none','retrieval_miss','stale_fact','false_fact')),
    expected jsonb NOT NULL,
    retrieved jsonb NOT NULL,
    score double precision NOT NULL,
    latency_ms double precision NOT NULL
);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_memories_updated_at ON memories;
CREATE TRIGGER trg_memories_updated_at
BEFORE UPDATE ON memories
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();
