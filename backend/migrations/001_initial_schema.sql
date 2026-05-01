CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
        CREATE TYPE user_role AS ENUM ('admin', 'executive', 'department_head', 'viewer');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'workflow_priority') THEN
        CREATE TYPE workflow_priority AS ENUM ('low', 'medium', 'high', 'critical');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'approval_status') THEN
        CREATE TYPE approval_status AS ENUM ('pending', 'approved', 'rejected');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'task_status') THEN
        CREATE TYPE task_status AS ENUM ('queued', 'in_progress', 'blocked', 'done');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS clients (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid REFERENCES clients(id) ON DELETE SET NULL,
    email text NOT NULL UNIQUE,
    full_name text NOT NULL,
    hashed_password text NOT NULL,
    role user_role NOT NULL DEFAULT 'viewer',
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS roles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name user_role NOT NULL UNIQUE,
    description text,
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO roles (name, description)
VALUES
    ('admin', 'Full system access'),
    ('executive', 'Submit objectives and approve decision reports'),
    ('department_head', 'View and update department tasks'),
    ('viewer', 'Read-only dashboard access')
ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS workflow_states (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid REFERENCES clients(id) ON DELETE CASCADE,
    objective_text text NOT NULL,
    department text NOT NULL,
    initiated_by uuid REFERENCES users(id) ON DELETE SET NULL,
    priority workflow_priority NOT NULL DEFAULT 'medium',
    approval_status approval_status NOT NULL DEFAULT 'pending',
    state_blob jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE workflow_states
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'created';

ALTER TABLE workflow_states
    ADD COLUMN IF NOT EXISTS reviewer_feedback text;

CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    id bigserial PRIMARY KEY,
    workflow_id uuid NOT NULL REFERENCES workflow_states(id) ON DELETE CASCADE,
    checkpoint_id integer NOT NULL,
    node_name text NOT NULL,
    state_blob jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workflow_id, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id uuid REFERENCES workflow_states(id) ON DELETE SET NULL,
    actor text NOT NULL,
    action text NOT NULL,
    input_summary text,
    output_summary text,
    duration_ms integer,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kb_domains (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name text NOT NULL,
    description text,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (client_id, name)
);

CREATE TABLE IF NOT EXISTS kb_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    domain_id uuid REFERENCES kb_domains(id) ON DELETE SET NULL,
    source_file text,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    embedding vector(768),
    embedding_model text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kb_ingestion_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    domain_id uuid REFERENCES kb_domains(id) ON DELETE SET NULL,
    filename text,
    file_type text,
    chunks_created integer NOT NULL DEFAULT 0,
    status text NOT NULL,
    error_detail text,
    ingested_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS department_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id uuid REFERENCES workflow_states(id) ON DELETE CASCADE,
    client_id uuid REFERENCES clients(id) ON DELETE CASCADE,
    department text NOT NULL,
    assigned_to uuid REFERENCES users(id) ON DELETE SET NULL,
    instructions text NOT NULL,
    required_actions jsonb NOT NULL DEFAULT '[]'::jsonb,
    deadline timestamptz,
    depends_on jsonb NOT NULL DEFAULT '[]'::jsonb,
    status task_status NOT NULL DEFAULT 'queued',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE department_tasks
    ALTER COLUMN workflow_id DROP NOT NULL;

CREATE TABLE IF NOT EXISTS notification_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id uuid REFERENCES workflow_states(id) ON DELETE SET NULL,
    task_id uuid REFERENCES department_tasks(id) ON DELETE SET NULL,
    client_id uuid REFERENCES clients(id) ON DELETE CASCADE,
    channel text NOT NULL,
    event_type text NOT NULL,
    recipient text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'queued',
    error_detail text,
    created_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_notification_events_workflow_id ON notification_events(workflow_id);
CREATE INDEX IF NOT EXISTS idx_notification_events_status ON notification_events(status);

CREATE INDEX IF NOT EXISTS idx_users_client_id ON users(client_id);
CREATE INDEX IF NOT EXISTS idx_workflow_states_client_id ON workflow_states(client_id);
CREATE INDEX IF NOT EXISTS idx_workflow_states_approval_status ON workflow_states(approval_status);
CREATE INDEX IF NOT EXISTS idx_workflow_checkpoints_workflow_id ON workflow_checkpoints(workflow_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_workflow_id ON audit_log(workflow_id);
CREATE INDEX IF NOT EXISTS idx_kb_domains_client_id ON kb_domains(client_id);
CREATE INDEX IF NOT EXISTS idx_kb_entries_client_domain ON kb_entries(client_id, domain_id);
CREATE INDEX IF NOT EXISTS idx_kb_ingestion_log_client_id ON kb_ingestion_log(client_id);
CREATE INDEX IF NOT EXISTS idx_department_tasks_client_status ON department_tasks(client_id, status);
CREATE INDEX IF NOT EXISTS idx_department_tasks_department ON department_tasks(department);

CREATE INDEX IF NOT EXISTS kb_embedding_idx
    ON kb_entries
    USING hnsw (embedding vector_cosine_ops);
