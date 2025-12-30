DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mercury_readonly') THEN
    CREATE ROLE mercury_readonly NOLOGIN;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mercury_readwrite') THEN
    CREATE ROLE mercury_readwrite NOLOGIN;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admin') THEN
    CREATE USER admin LOGIN PASSWORD 'admin';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'flyway_user') THEN
    CREATE USER flyway_user LOGIN PASSWORD 'flywaypass';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'catalog_service') THEN
    CREATE USER catalog_service LOGIN PASSWORD 'catalogpass';
  END IF;
END $$;

GRANT mercury_readwrite TO admin;
GRANT mercury_readwrite TO catalog_service;

CREATE SCHEMA IF NOT EXISTS mercury AUTHORIZATION admin;
ALTER SCHEMA mercury OWNER TO admin;

GRANT USAGE ON SCHEMA mercury TO mercury_readonly;
GRANT USAGE ON SCHEMA mercury TO mercury_readwrite;
GRANT USAGE, CREATE ON SCHEMA mercury TO flyway_user;

REVOKE CREATE ON SCHEMA mercury FROM mercury_readonly;
REVOKE CREATE ON SCHEMA mercury FROM mercury_readwrite;

GRANT SELECT ON ALL TABLES IN SCHEMA mercury TO mercury_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA mercury TO mercury_readwrite;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA mercury TO mercury_readwrite;

ALTER DEFAULT PRIVILEGES FOR ROLE flyway_user IN SCHEMA mercury
  GRANT SELECT ON TABLES TO mercury_readonly;

ALTER DEFAULT PRIVILEGES FOR ROLE flyway_user IN SCHEMA mercury
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mercury_readwrite;

ALTER DEFAULT PRIVILEGES FOR ROLE flyway_user IN SCHEMA mercury
  GRANT USAGE, SELECT ON SEQUENCES TO mercury_readwrite;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;