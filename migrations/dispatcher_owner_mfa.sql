CREATE TABLE IF NOT EXISTS private_drive_dispatcher_mfa (
    admin_id bigint PRIMARY KEY,
    attempt_window bigint NOT NULL,
    attempts integer NOT NULL CHECK (attempts BETWEEN 1 AND 5),
    last_counter bigint NOT NULL DEFAULT -1
);
