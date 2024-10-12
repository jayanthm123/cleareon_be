CREATE TABLE distribution_lists (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    emails TEXT[] NOT NULL,
    ccEmails TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create an index on the name column for faster lookups
CREATE INDEX idx_distribution_lists_name ON distribution_lists(name);