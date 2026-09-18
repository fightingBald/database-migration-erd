-- Exercise table/column renames and index maintenance.
ALTER TABLE demo_library.loan_requests RENAME TO loans;

ALTER TABLE demo_library.loans RENAME COLUMN state TO loan_state;
ALTER TABLE demo_library.loans ADD COLUMN loan_label TEXT;
ALTER TABLE demo_library.loans DROP COLUMN loan_label;

CREATE INDEX idx_loans_member ON demo_library.loans (member_id);
ALTER INDEX idx_loans_member RENAME TO idx_loans_memberid;
DROP INDEX idx_loans_memberid;

CREATE UNIQUE INDEX idx_loan_items_book_partial ON demo_library.loan_items (book_id) WHERE copy_count > 1;
