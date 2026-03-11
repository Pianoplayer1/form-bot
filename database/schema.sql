CREATE TABLE forms (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    message      TEXT,
    confirmation TEXT,
    channel      BIGINT,
    ping         BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE modals (
    id      SERIAL PRIMARY KEY,
    form_id INTEGER NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
    label   TEXT NOT NULL,
    title   TEXT,
    UNIQUE (form_id, label)
);

CREATE TABLE questions (
    id          SERIAL PRIMARY KEY,
    modal_id    INTEGER NOT NULL REFERENCES modals(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    description TEXT,
    placeholder TEXT,
    paragraph   BOOLEAN NOT NULL DEFAULT FALSE,
    required    BOOLEAN NOT NULL DEFAULT TRUE,
    min_length           INTEGER,
    max_length           INTEGER,
    minecraft_username   BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (modal_id, label)
);

-- Enforce max 5 questions per modal at the database level.
CREATE OR REPLACE FUNCTION check_question_limit()
RETURNS TRIGGER AS $$
BEGIN
    IF (SELECT COUNT(*) FROM questions WHERE modal_id = NEW.modal_id) >= 5 THEN
        RAISE EXCEPTION 'A modal cannot have more than 5 questions';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_question_limit
    BEFORE INSERT ON questions
    FOR EACH ROW
    EXECUTE FUNCTION check_question_limit();

CREATE TABLE responses (
    id        SERIAL PRIMARY KEY,
    username  TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    form_id   INTEGER NOT NULL REFERENCES forms(id) ON DELETE CASCADE
);

CREATE INDEX idx_responses_form_id ON responses(form_id);

CREATE TABLE answers (
    response_id INTEGER NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    answer      TEXT,
    PRIMARY KEY (response_id, question_id)
);

CREATE TABLE form_views (
    id         SERIAL PRIMARY KEY,
    message_id BIGINT NOT NULL,
    label      TEXT NOT NULL,
    emoji      TEXT,
    style      INTEGER NOT NULL,
    form_id    INTEGER NOT NULL REFERENCES forms(id) ON DELETE CASCADE
);

CREATE INDEX idx_form_views_message_id ON form_views(message_id);

-- Speed up ILIKE autocomplete queries.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_forms_name_trgm ON forms USING gin (name gin_trgm_ops);
CREATE INDEX idx_modals_label_trgm ON modals USING gin (label gin_trgm_ops);
CREATE INDEX idx_questions_label_trgm ON questions USING gin (label gin_trgm_ops);
