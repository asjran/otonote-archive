-- 0001_bindings.sql — initial schema for the lightweight identity binding
-- module. Creates the ``bindings`` table with the unique constraint from
-- design §9.2 and a separate ``schema_version`` row used by the runtime
-- to skip already-applied migrations.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity_namespace TEXT NOT NULL,
    platform_user_id TEXT NOT NULL,
    game_environment_id TEXT NOT NULL,
    game_account_id TEXT NOT NULL,
    verification_status TEXT NOT NULL
        CHECK (verification_status IN ('claimed', 'verified', 'revoked')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (identity_namespace, platform_user_id, game_environment_id)
);

CREATE INDEX IF NOT EXISTS idx_bindings_environment
    ON bindings (game_environment_id);

CREATE INDEX IF NOT EXISTS idx_bindings_identity
    ON bindings (identity_namespace, platform_user_id);