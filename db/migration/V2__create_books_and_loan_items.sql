CREATE TABLE demo_library.books (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    published_year INTEGER NOT NULL
);

CREATE TABLE demo_library.loan_items (
    loan_id BIGINT NOT NULL, -- FK demo_library.loan_requests(id)
    book_id BIGINT NOT NULL, -- FK demo_library.books(id)
    copy_count INTEGER NOT NULL DEFAULT 1,
    renewal_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (loan_id, book_id)
);
