-- ============================================================================
-- Answer feedback events + quality snapshots (Candidate 2 foundation)
-- Migration: 009_answer_feedback_quality.sql
-- Created: 2026-04-27
-- Purpose: Persist append-only answer feedback and maintain lightweight
--          answer-quality snapshots for admin/QA metrics.
-- ============================================================================

CREATE TABLE IF NOT EXISTS answer_feedback_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    answer_message_id UUID NOT NULL REFERENCES chat_messages(id) ON DELETE RESTRICT,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE RESTRICT,
    source_message_id UUID REFERENCES chat_messages(id) ON DELETE SET NULL,
    actor_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sentiment VARCHAR(8) NOT NULL CHECK (sentiment IN ('up', 'down')),
    reason_code VARCHAR(80),
    comment TEXT,
    system_scope VARCHAR(255),
    area_scope VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_answer_feedback_events_answer_message
    ON answer_feedback_events(answer_message_id);
CREATE INDEX IF NOT EXISTS idx_answer_feedback_events_conversation
    ON answer_feedback_events(conversation_id);
CREATE INDEX IF NOT EXISTS idx_answer_feedback_events_actor_user
    ON answer_feedback_events(actor_user_id);
CREATE INDEX IF NOT EXISTS idx_answer_feedback_events_sentiment_created
    ON answer_feedback_events(sentiment, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_answer_feedback_events_scope_created
    ON answer_feedback_events(
        COALESCE(LOWER(system_scope), ''),
        COALESCE(LOWER(area_scope), ''),
        created_at DESC
    );

CREATE TABLE IF NOT EXISTS answer_quality_snapshots (
    answer_message_id UUID PRIMARY KEY REFERENCES chat_messages(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE RESTRICT,
    system_scope VARCHAR(255),
    area_scope VARCHAR(255),
    feedback_count INTEGER NOT NULL DEFAULT 0,
    positive_count INTEGER NOT NULL DEFAULT 0,
    negative_count INTEGER NOT NULL DEFAULT 0,
    negative_streak INTEGER NOT NULL DEFAULT 0,
    quality_score NUMERIC(8,4) NOT NULL DEFAULT 0,
    is_flagged BOOLEAN NOT NULL DEFAULT FALSE,
    last_feedback_at TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_answer_quality_snapshots_flagged
    ON answer_quality_snapshots(is_flagged, last_feedback_at DESC);
CREATE INDEX IF NOT EXISTS idx_answer_quality_snapshots_scope
    ON answer_quality_snapshots(
        COALESCE(LOWER(system_scope), ''),
        COALESCE(LOWER(area_scope), '')
    );

-- Append-only protection for feedback events.
CREATE OR REPLACE FUNCTION prevent_answer_feedback_event_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'answer_feedback_events is append-only and does not allow %', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_answer_feedback_events_no_update ON answer_feedback_events;
CREATE TRIGGER trg_answer_feedback_events_no_update
BEFORE UPDATE ON answer_feedback_events
FOR EACH ROW
EXECUTE FUNCTION prevent_answer_feedback_event_mutation();

DROP TRIGGER IF EXISTS trg_answer_feedback_events_no_delete ON answer_feedback_events;
CREATE TRIGGER trg_answer_feedback_events_no_delete
BEFORE DELETE ON answer_feedback_events
FOR EACH ROW
EXECUTE FUNCTION prevent_answer_feedback_event_mutation();

GRANT SELECT, INSERT ON answer_feedback_events TO plantig_user, plantig_reviewer, plantig_admin;
GRANT SELECT, INSERT, UPDATE ON answer_quality_snapshots TO plantig_user, plantig_reviewer, plantig_admin;

ALTER TABLE answer_feedback_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE answer_quality_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY answer_feedback_events_insert_own ON answer_feedback_events FOR INSERT
  TO plantig_user, plantig_reviewer, plantig_admin
  WITH CHECK (actor_user_id = plantig_uid() OR plantig_role() = 'plantig_admin');

CREATE POLICY answer_feedback_events_select_own ON answer_feedback_events FOR SELECT
  TO plantig_user, plantig_reviewer
  USING (actor_user_id = plantig_uid());

CREATE POLICY answer_feedback_events_admin_all ON answer_feedback_events FOR ALL
  TO plantig_admin
  USING (true)
  WITH CHECK (true);

CREATE POLICY answer_quality_snapshots_select_scoped ON answer_quality_snapshots FOR SELECT
  TO plantig_user, plantig_reviewer
  USING (
    conversation_id IN (
      SELECT id FROM conversations WHERE user_id = plantig_uid()
    )
  );

CREATE POLICY answer_quality_snapshots_upsert_scoped ON answer_quality_snapshots FOR INSERT
  TO plantig_user, plantig_reviewer, plantig_admin
  WITH CHECK (
    plantig_role() = 'plantig_admin'
    OR conversation_id IN (
      SELECT id FROM conversations WHERE user_id = plantig_uid()
    )
  );

CREATE POLICY answer_quality_snapshots_update_scoped ON answer_quality_snapshots FOR UPDATE
  TO plantig_user, plantig_reviewer, plantig_admin
  USING (
    plantig_role() = 'plantig_admin'
    OR conversation_id IN (
      SELECT id FROM conversations WHERE user_id = plantig_uid()
    )
  )
  WITH CHECK (
    plantig_role() = 'plantig_admin'
    OR conversation_id IN (
      SELECT id FROM conversations WHERE user_id = plantig_uid()
    )
  );

CREATE POLICY answer_quality_snapshots_admin_all ON answer_quality_snapshots FOR ALL
  TO plantig_admin
  USING (true)
  WITH CHECK (true);

-- ============================================================================
-- END OF MIGRATION
-- ============================================================================
