CREATE ROLE mercury_readonly NOLOGIN;
CREATE ROLE mercury_readwrite NOLOGIN;

CREATE USER flyway_user WITH LOGIN PASSWORD 'flywaypass';
CREATE USER admin WITH LOGIN PASSWORD 'admin';
CREATE USER catalog_service WITH LOGIN PASSWORD 'catalogpass';

GRANT mercury_readwrite TO flyway_user;
GRANT mercury_readwrite TO admin;
GRANT mercury_readonly TO catalog_service;

CREATE SCHEMA IF NOT EXISTS mercury AUTHORIZATION flyway_user;

GRANT USAGE, CREATE ON SCHEMA mercury TO mercury_readwrite;
GRANT USAGE ON SCHEMA mercury TO mercury_readonly;

GRANT SELECT ON ALL TABLES IN SCHEMA mercury TO mercury_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA mercury TO mercury_readwrite;

ALTER DEFAULT PRIVILEGES FOR ROLE flyway_user IN SCHEMA mercury
  GRANT SELECT ON TABLES TO mercury_readonly;

ALTER DEFAULT PRIVILEGES FOR ROLE flyway_user IN SCHEMA mercury
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mercury_readwrite;
  
-- If you use identity/serial sequences (recommended)
ALTER DEFAULT PRIVILEGES FOR ROLE flyway_user IN SCHEMA mercury
    GRANT USAGE, SELECT ON SEQUENCES TO mercury_readwrite;