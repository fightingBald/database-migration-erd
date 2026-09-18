-- Leave these relationships for the optional YAML override example.
CREATE TABLE demo_library.membership_types (
    id BIGSERIAL PRIMARY KEY,
    type_name TEXT NOT NULL UNIQUE
);

ALTER TABLE demo_library.members
    ADD COLUMN membership_type_id BIGINT,
    ADD COLUMN sponsor_id BIGINT;
