-- Synthetic 30-table library with four business families.

CREATE SCHEMA demo_library;

CREATE TABLE demo_library.books (
    id BIGINT PRIMARY KEY,
    title TEXT NOT NULL,
    isbn TEXT UNIQUE,
    published_year INT,
    created_at TIMESTAMPTZ
);

CREATE TABLE demo_library.books_editions (
    id BIGINT PRIMARY KEY,
    book_id BIGINT REFERENCES demo_library.books(id),
    edition_number INT,
    language TEXT,
    publisher TEXT
);

CREATE TABLE demo_library.books_copies (
    id BIGINT PRIMARY KEY,
    edition_id BIGINT REFERENCES demo_library.books_editions(id),
    branch_id BIGINT REFERENCES demo_library.branches(id),
    barcode TEXT UNIQUE,
    status TEXT
);

CREATE TABLE demo_library.books_authors (
    id BIGINT PRIMARY KEY,
    display_name TEXT,
    biography TEXT
);

CREATE TABLE demo_library.books_author_links (
    book_id BIGINT REFERENCES demo_library.books(id),
    author_id BIGINT REFERENCES demo_library.books_authors(id),
    author_order INT,
    PRIMARY KEY (book_id, author_id)
);

CREATE TABLE demo_library.books_genres (
    id BIGINT PRIMARY KEY,
    name TEXT,
    description TEXT
);

CREATE TABLE demo_library.books_genre_links (
    book_id BIGINT REFERENCES demo_library.books(id),
    genre_id BIGINT REFERENCES demo_library.books_genres(id),
    PRIMARY KEY (book_id, genre_id)
);

CREATE TABLE demo_library.books_reviews (
    id BIGINT PRIMARY KEY,
    book_id BIGINT REFERENCES demo_library.books(id),
    rating INT,
    review_text TEXT,
    created_at TIMESTAMPTZ
);

CREATE TABLE demo_library.members (
    id BIGINT PRIMARY KEY,
    display_name TEXT,
    email TEXT UNIQUE,
    joined_at TIMESTAMPTZ,
    status TEXT
);

CREATE TABLE demo_library.members_profiles (
    id BIGINT PRIMARY KEY,
    member_id BIGINT REFERENCES demo_library.members(id),
    locale TEXT,
    biography TEXT
);

CREATE TABLE demo_library.members_contacts (
    id BIGINT PRIMARY KEY,
    member_id BIGINT REFERENCES demo_library.members(id),
    channel TEXT,
    contact_value TEXT
);

CREATE TABLE demo_library.members_addresses (
    id BIGINT PRIMARY KEY,
    member_id BIGINT REFERENCES demo_library.members(id),
    city TEXT,
    postal_code TEXT
);

CREATE TABLE demo_library.members_cards (
    id BIGINT PRIMARY KEY,
    member_id BIGINT REFERENCES demo_library.members(id),
    card_number TEXT UNIQUE,
    expires_at TIMESTAMPTZ
);

CREATE TABLE demo_library.members_preferences (
    id BIGINT PRIMARY KEY,
    member_id BIGINT REFERENCES demo_library.members(id),
    preference_key TEXT,
    preference_value TEXT
);

CREATE TABLE demo_library.members_roles (
    id BIGINT PRIMARY KEY,
    name TEXT,
    loan_limit INT
);

CREATE TABLE demo_library.members_role_links (
    member_id BIGINT REFERENCES demo_library.members(id),
    role_id BIGINT REFERENCES demo_library.members_roles(id),
    assigned_at TIMESTAMPTZ,
    PRIMARY KEY (member_id, role_id)
);

CREATE TABLE demo_library.loans (
    id BIGINT PRIMARY KEY,
    member_id BIGINT REFERENCES demo_library.members(id),
    branch_id BIGINT REFERENCES demo_library.branches(id),
    started_at TIMESTAMPTZ,
    due_at TIMESTAMPTZ,
    status TEXT
);

CREATE TABLE demo_library.loans_items (
    id BIGINT PRIMARY KEY,
    loan_id BIGINT REFERENCES demo_library.loans(id),
    copy_id BIGINT REFERENCES demo_library.books_copies(id),
    checked_out_at TIMESTAMPTZ
);

CREATE TABLE demo_library.loans_renewals (
    id BIGINT PRIMARY KEY,
    item_id BIGINT REFERENCES demo_library.loans_items(id),
    renewed_at TIMESTAMPTZ,
    new_due_at TIMESTAMPTZ
);

CREATE TABLE demo_library.loans_returns (
    id BIGINT PRIMARY KEY,
    item_id BIGINT REFERENCES demo_library.loans_items(id),
    returned_at TIMESTAMPTZ,
    condition TEXT
);

CREATE TABLE demo_library.loans_fines (
    id BIGINT PRIMARY KEY,
    loan_id BIGINT REFERENCES demo_library.loans(id),
    return_id BIGINT REFERENCES demo_library.loans_returns(id),
    amount NUMERIC(10,2),
    settled BOOLEAN
);

CREATE TABLE demo_library.loans_holds (
    id BIGINT PRIMARY KEY,
    loan_id BIGINT REFERENCES demo_library.loans(id),
    book_id BIGINT REFERENCES demo_library.books(id),
    reserved_at TIMESTAMPTZ
);

CREATE TABLE demo_library.loans_notifications (
    id BIGINT PRIMARY KEY,
    loan_id BIGINT REFERENCES demo_library.loans(id),
    channel TEXT,
    sent_at TIMESTAMPTZ
);

CREATE TABLE demo_library.branches (
    id BIGINT PRIMARY KEY,
    name TEXT,
    city TEXT,
    opened_at TIMESTAMPTZ
);

CREATE TABLE demo_library.branches_rooms (
    id BIGINT PRIMARY KEY,
    branch_id BIGINT REFERENCES demo_library.branches(id),
    room_name TEXT,
    capacity INT
);

CREATE TABLE demo_library.branches_shelves (
    id BIGINT PRIMARY KEY,
    branch_id BIGINT REFERENCES demo_library.branches(id),
    room_id BIGINT REFERENCES demo_library.branches_rooms(id),
    shelf_code TEXT
);

CREATE TABLE demo_library.branches_opening_hours (
    id BIGINT PRIMARY KEY,
    branch_id BIGINT REFERENCES demo_library.branches(id),
    weekday INT,
    opens_at TIME,
    closes_at TIME
);

CREATE TABLE demo_library.branches_staff (
    id BIGINT PRIMARY KEY,
    branch_id BIGINT REFERENCES demo_library.branches(id),
    display_name TEXT,
    shift_name TEXT
);

CREATE TABLE demo_library.branches_services (
    id BIGINT PRIMARY KEY,
    branch_id BIGINT REFERENCES demo_library.branches(id),
    service_name TEXT,
    duration_minutes INT
);

CREATE TABLE demo_library.branches_service_slots (
    id BIGINT PRIMARY KEY,
    service_id BIGINT REFERENCES demo_library.branches_services(id),
    room_id BIGINT REFERENCES demo_library.branches_rooms(id),
    starts_at TIMESTAMPTZ,
    available BOOLEAN
);
