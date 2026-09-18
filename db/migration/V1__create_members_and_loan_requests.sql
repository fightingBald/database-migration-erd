-- Entirely fictional library data for parser and diagram examples.
CREATE SCHEMA demo_library;

CREATE TABLE demo_library.members (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE demo_library.loan_requests (
    id BIGSERIAL PRIMARY KEY,
    member_id BIGINT NOT NULL REFERENCES demo_library.members(id),
    state TEXT NOT NULL,
    due_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
