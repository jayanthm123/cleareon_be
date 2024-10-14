CREATE TABLE distribution_lists (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    emails TEXT[] NOT NULL,
    ccEmails TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create an index on the name column for faster lookups
CREATE INDEX idx_distribution_lists_name ON distribution_lists(name);

CREATE TABLE inquiry_details (
    id SERIAL PRIMARY KEY,
    sent_on TIMESTAMP NOT NULL,
    subject VARCHAR(255) NOT NULL,
    distribution_name VARCHAR(100) NOT NULL,
	sent_to INTEGER DEFAULT 0,
	status  VARCHAR(100) NOT NULL,
    responses_received INTEGER DEFAULT 0,
    lowest_quote DECIMAL(10, 2),
	mail_content TEXT
);
