-- Football Recruitment Intelligence System — core schema (v1)
-- Design notes:
--   * teams/players are deduplicated across matches (Wyscout repeats them per match file).
--   * events is the raw, typed event log — one row per on-ball action.
--   * player_match_minutes is derived during ingestion from substitution events,
--     since Wyscout does not give an explicit "minutes played" field.
--   * No separate `positions` or `tactical_profiles` tables in v1: role is a
--     column on players (coarse, from source) and a derived column added later
--     in feature engineering (fine-grained, from event-location clustering).

CREATE TABLE IF NOT EXISTS teams (
    team_id      BIGINT PRIMARY KEY,
    name         VARCHAR NOT NULL,
    official_name VARCHAR,
    country      VARCHAR
);

CREATE TABLE IF NOT EXISTS players (
    player_id       BIGINT PRIMARY KEY,
    first_name      VARCHAR,
    last_name       VARCHAR,
    short_name      VARCHAR,
    birth_date      DATE,
    height_cm       INTEGER,
    weight_kg       INTEGER,
    foot            VARCHAR,
    role_code       VARCHAR,     -- coarse source role: GK / DF / MD / FW
    role_name       VARCHAR,
    birth_country   VARCHAR,
    current_team_id BIGINT
);

CREATE TABLE IF NOT EXISTS matches (
    match_id        BIGINT PRIMARY KEY,
    competition     VARCHAR NOT NULL,   -- e.g. "England", "Spain"
    season          VARCHAR NOT NULL,   -- e.g. "2017/18"
    label           VARCHAR,
    home_team_id    BIGINT,
    away_team_id    BIGINT,
    match_date      TIMESTAMP,
    ingested_at     TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS events (
    event_id        BIGINT PRIMARY KEY,   -- Wyscout's global event id
    match_id        BIGINT NOT NULL,
    team_id         BIGINT,
    player_id       BIGINT,
    match_period    VARCHAR,              -- '1H' / '2H' / extra time
    event_sec       DOUBLE,                -- seconds into the period
    event_name      VARCHAR,               -- e.g. "Pass", "Duel"
    sub_event_name  VARCHAR,               -- e.g. "Simple pass", "Air duel"
    start_x         DOUBLE,                -- 0-100 pitch coordinate
    start_y         DOUBLE,
    end_x           DOUBLE,
    end_y           DOUBLE,
    tags            VARCHAR,               -- JSON-encoded list of tag ids (raw, parsed later)
    FOREIGN KEY (match_id) REFERENCES matches(match_id)
);

CREATE TABLE IF NOT EXISTS player_match_participation (
    match_id        BIGINT NOT NULL,
    player_id       BIGINT NOT NULL,
    team_id         BIGINT NOT NULL,
    is_starter      BOOLEAN,
    minutes_played  DOUBLE,             -- derived from sub events; NULL until computed
    PRIMARY KEY (match_id, player_id)
);

-- Basic integrity/quality view used by validation tests.
CREATE OR REPLACE VIEW v_events_missing_player AS
SELECT * FROM events WHERE player_id IS NULL;
