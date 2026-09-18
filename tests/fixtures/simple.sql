CREATE TABLE demo_library.members (
    id INT PRIMARY KEY,
    sponsor_id INT REFERENCES demo_library.members(id)
);
