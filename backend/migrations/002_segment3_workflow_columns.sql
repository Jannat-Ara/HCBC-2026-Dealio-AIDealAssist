ALTER TABLE workflow_states
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'created';

ALTER TABLE workflow_states
    ADD COLUMN IF NOT EXISTS reviewer_feedback text;

ALTER TABLE department_tasks
    ALTER COLUMN workflow_id DROP NOT NULL;
