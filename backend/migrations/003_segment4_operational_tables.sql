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
