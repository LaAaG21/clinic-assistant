-- Pending staff approvals (#40). Requests are owned by 004_requests.sql (#52).
-- 005 is reserved for the messages/request-FK portion of #26.
CREATE TABLE approvals (
    approval_id text PRIMARY KEY,
    request_id text NOT NULL UNIQUE REFERENCES requests (request_id),
    decision text,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz,
    CONSTRAINT approvals_id_not_blank CHECK (btrim(approval_id) <> ''),
    CONSTRAINT approvals_decision_complete CHECK (
        (decision IS NULL AND reason IS NULL AND decided_at IS NULL)
        OR (
            decision IS NOT NULL AND decision IN ('approve', 'reject')
            AND reason IS NOT NULL AND btrim(reason) <> ''
            AND char_length(reason) BETWEEN 1 AND 1000
            AND decided_at IS NOT NULL
        )
    ),
    CONSTRAINT approvals_decided_at_valid CHECK (
        decided_at IS NULL OR decided_at >= created_at
    )
);

CREATE INDEX approvals_pending_order ON approvals (created_at, approval_id)
    WHERE decision IS NULL;
