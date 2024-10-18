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

CREATE TABLE IF NOT EXISTS failed_emails (
    id SERIAL PRIMARY KEY,
    inquiry_id INTEGER NOT NULL,
    tried_on TIMESTAMP NOT NULL,
    subject TEXT NOT NULL,
    to_email TEXT NOT NULL,
    cc TEXT,
    mail_content TEXT NOT NULL
);

CREATE TABLE processed_emails (
    id SERIAL PRIMARY KEY,
    message_id TEXT UNIQUE NOT NULL,
    subject TEXT,
    sender TEXT,
    recipient TEXT,
    cc TEXT[],
    bcc TEXT[],
    received_date TIMESTAMP WITH TIME ZONE,
    processed_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    body_text TEXT,
    body_html TEXT,
    headers JSONB,
    attachments JSONB,
    is_processed BOOLEAN DEFAULT FALSE,
    processing_status TEXT,
    folder TEXT
);
CREATE INDEX idx_message_id ON processed_emails(message_id);
CREATE INDEX idx_received_date ON processed_emails(received_date);
CREATE INDEX idx_processed_date ON processed_emails(processed_date);
CREATE INDEX idx_is_processed ON processed_emails(is_processed);
CREATE INDEX idx_sender ON processed_emails(sender);
CREATE INDEX idx_subject ON processed_emails(subject);

-- SQL query to create the client_config table
CREATE TABLE IF NOT EXISTS client_config (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(50) NOT NULL,
    client_account_id VARCHAR(50) NOT NULL,
    config_key VARCHAR(100) NOT NULL,
    config_value TEXT,
    UNIQUE (client_id, client_account_id, config_key)
);

-- Insert initial records for email refresh datetime if they don't exist
INSERT INTO client_config (client_id, client_account_id, config_key, config_value)
VALUES
    ('default', 'default', 'last_refresh_datetime', '1970-01-01 00:00:00+00'),
    ('default', 'default', 'imap_server', 'imap.example.com'),
    ('default', 'default', 'email_address', 'user@example.com'),
    ('default', 'default', 'email_password', 'your_password_here')
ON CONFLICT (client_id, client_account_id, config_key) DO NOTHING;

-- Table: public.failed_emails

-- DROP TABLE IF EXISTS public.failed_emails;

-- Table: public.failed_emails

-- DROP TABLE IF EXISTS public.failed_emails;

CREATE TABLE IF NOT EXISTS public.inquiry_emails_sent
(
    id SERIAL PRIMARY KEY,
    inquiry_id integer NOT NULL,
	message_id TEXT,
    sent_on timestamp without time zone NOT NULL,
    subject text COLLATE pg_catalog."default" NOT NULL,
    to_email text COLLATE pg_catalog."default" NOT NULL,
    cc text COLLATE pg_catalog."default"
)

Select * from processed_emails

alter table processed_emails add column isReplyProcessed BOOLEAN DEFAULT FALSE;
alter table  inquiry_emails_sent  add column  reply_mail_id INTEGER

select * from inquiry_emails_sent

update inquiry_emails_sent set reply_mail_id = null

update processed_emails set isReplyProcessed = false