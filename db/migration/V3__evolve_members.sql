-- Exercise ALTER TABLE branches on the fictional member table.
ALTER TABLE demo_library.members ADD COLUMN status TEXT;
ALTER TABLE demo_library.members ALTER COLUMN status TYPE VARCHAR(16);
ALTER TABLE demo_library.members ALTER COLUMN status SET NOT NULL;

ALTER TABLE demo_library.members ADD COLUMN last_visit TIMESTAMPTZ;
ALTER TABLE demo_library.members DROP COLUMN last_visit;

ALTER TABLE demo_library.members RENAME COLUMN name TO full_name;

ALTER TABLE demo_library.members ADD CONSTRAINT members_email_unique UNIQUE (email);
ALTER TABLE demo_library.members DROP CONSTRAINT members_email_unq;
ALTER TABLE demo_library.members ADD CONSTRAINT members_email_status_unique UNIQUE (email, status);

CREATE UNIQUE INDEX idx_members_active_email ON demo_library.members USING btree (email, status) WHERE status <> 'inactive';
CREATE INDEX idx_members_lower_email ON demo_library.members (LOWER(email));
