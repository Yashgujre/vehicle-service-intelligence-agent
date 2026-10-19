-- Runs once, on first start of an empty Postgres data volume (docker-entrypoint-initdb.d).
-- Creates one database and one login role per service. Passwords come from the container environment
-- through psql's \getenv (PostgreSQL 15+), so no secret is written in this file.
-- The mlflow database is created even though MLflow starts on SQLite (ADR-0081), so switching the
-- MLflow backend to Postgres later is a one-line change.

\set ON_ERROR_STOP on

\getenv vsia_pw VSIA_DB_PASSWORD
\getenv n8n_pw N8N_DB_PASSWORD
\getenv mlflow_pw MLFLOW_DB_PASSWORD

CREATE ROLE vsia LOGIN PASSWORD :'vsia_pw';
CREATE ROLE n8n LOGIN PASSWORD :'n8n_pw';
CREATE ROLE mlflow LOGIN PASSWORD :'mlflow_pw';

CREATE DATABASE vsia OWNER vsia;
CREATE DATABASE n8n OWNER n8n;
CREATE DATABASE mlflow OWNER mlflow;

REVOKE ALL ON DATABASE vsia FROM PUBLIC;
REVOKE ALL ON DATABASE n8n FROM PUBLIC;
REVOKE ALL ON DATABASE mlflow FROM PUBLIC;

-- Postgres 15+ no longer grants CREATE on the public schema to every role; give each owner its schema.
\connect vsia
ALTER SCHEMA public OWNER TO vsia;
\connect n8n
ALTER SCHEMA public OWNER TO n8n;
\connect mlflow
ALTER SCHEMA public OWNER TO mlflow;
