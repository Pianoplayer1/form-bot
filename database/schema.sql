CREATE TABLE forms
(
    id           SMALLSERIAL PRIMARY KEY,
    name         VARCHAR(45) NOT NULL UNIQUE,
    message      VARCHAR(2000),
    confirmation VARCHAR(2000),
    channel      BIGINT,
    ping         BOOLEAN     NOT NULL DEFAULT FALSE
);

CREATE TABLE pages
(
    id      SMALLSERIAL PRIMARY KEY,
    form_id SMALLINT    NOT NULL REFERENCES forms ON DELETE CASCADE,
    label   VARCHAR(80) NOT NULL,
    title   VARCHAR(45),
    UNIQUE (form_id, label)
);

CREATE TABLE questions
(
    id                 SMALLSERIAL PRIMARY KEY,
    page_id            SMALLINT    NOT NULL REFERENCES pages ON DELETE CASCADE,
    label              VARCHAR(45) NOT NULL,
    description        VARCHAR(100),
    placeholder        VARCHAR(100),
    paragraph          BOOLEAN     NOT NULL DEFAULT FALSE,
    required           BOOLEAN     NOT NULL DEFAULT TRUE,
    min_length         SMALLINT,
    max_length         SMALLINT,
    minecraft_username BOOLEAN     NOT NULL DEFAULT FALSE,
    UNIQUE (page_id, label)
);

CREATE TABLE responses
(
    id        SMALLSERIAL PRIMARY KEY,
    username  VARCHAR(32) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    form_id   SMALLINT    NOT NULL REFERENCES forms ON DELETE CASCADE
);
CREATE INDEX idx_responses_form_id ON responses (form_id);

CREATE TABLE answers
(
    response_id SMALLINT NOT NULL REFERENCES responses ON DELETE CASCADE,
    question_id SMALLINT NOT NULL REFERENCES questions ON DELETE SET NULL,
    answer      VARCHAR(4000),
    PRIMARY KEY (response_id, question_id)
);

CREATE TABLE form_views
(
    id         SMALLSERIAL PRIMARY KEY,
    message_id BIGINT      NOT NULL,
    label      VARCHAR(80) NOT NULL,
    emoji      VARCHAR(32),
    style      SMALLINT    NOT NULL,
    form_id    SMALLINT    NOT NULL REFERENCES forms ON DELETE CASCADE,
    UNIQUE (message_id, label)
);
CREATE INDEX idx_form_views_message_id ON form_views (message_id);

-- Speed up ILIKE autocomplete queries.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_forms_name_trgm ON forms USING gin (name gin_trgm_ops);
CREATE INDEX idx_pages_label_trgm ON pages USING gin (label gin_trgm_ops);
CREATE INDEX idx_questions_label_trgm ON questions USING gin (label gin_trgm_ops);
