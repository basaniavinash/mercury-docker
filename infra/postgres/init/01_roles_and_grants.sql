-- Fail fast if anything errors
\set ON_ERROR_STOP on

-- ------------------------------------------------------------------------------------
-- 0) HARDEN DEFAULTS (does not break anything because we re-grant explicitly)
-- ------------------------------------------------------------------------------------
REVOKE ALL ON DATABASE mercury FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- ------------------------------------------------------------------------------------
-- 1) ROLES + USERS
-- ------------------------------------------------------------------------------------
DO $$
BEGIN
  -- group roles
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mercury_readonly') THEN
    CREATE ROLE mercury_readonly NOLOGIN;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mercury_readwrite') THEN
    CREATE ROLE mercury_readwrite NOLOGIN;
  END IF;

  -- login roles
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admin') THEN
    CREATE ROLE admin LOGIN PASSWORD 'admin';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'flyway_user') THEN
    CREATE ROLE flyway_user LOGIN PASSWORD 'flywaypass';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'catalog_service') THEN
    CREATE ROLE catalog_service LOGIN PASSWORD 'catalogpass';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'order_service') THEN
    CREATE ROLE order_service LOGIN PASSWORD 'orderpass';
  END IF;
END $$;

-- Memberships (apps inherit CRUD privileges via mercury_readwrite)
GRANT mercury_readwrite TO admin;
GRANT mercury_readwrite TO catalog_service;
GRANT mercury_readwrite TO order_service;

-- ------------------------------------------------------------------------------------
-- 2) DATABASE-LEVEL PRIVILEGES (THIS is what your error is about)
-- ------------------------------------------------------------------------------------
-- Ensure the roles can connect (and optionally create temp tables)
GRANT CONNECT, TEMP ON DATABASE mercury TO admin;
GRANT CONNECT, TEMP ON DATABASE mercury TO flyway_user;
GRANT CONNECT, TEMP ON DATABASE mercury TO catalog_service;
GRANT CONNECT, TEMP ON DATABASE mercury TO order_service;

-- (Optional sanity) ensure PUBLIC truly has nothing
REVOKE ALL ON DATABASE mercury FROM PUBLIC;

-- ------------------------------------------------------------------------------------
-- 3) SCHEMA OWNERSHIP + PRIVS
--    Make Flyway own the schema so migrations "just work" without extra DDL gymnastics.
-- ------------------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS mercury AUTHORIZATION flyway_user;
ALTER SCHEMA mercury OWNER TO flyway_user;

-- allow app roles to use objects in schema
GRANT USAGE ON SCHEMA mercury TO mercury_readonly;
GRANT USAGE ON SCHEMA mercury TO mercury_readwrite;

-- allow flyway to create/alter objects in schema
GRANT USAGE, CREATE ON SCHEMA mercury TO flyway_user;

-- explicitly prevent apps from doing DDL
REVOKE CREATE ON SCHEMA mercury FROM mercury_readonly;
REVOKE CREATE ON SCHEMA mercury FROM mercury_readwrite;

-- ------------------------------------------------------------------------------------
-- 4) OBJECT PRIVS (existing objects) + DEFAULT PRIVS (future objects)
-- ------------------------------------------------------------------------------------
-- Existing objects (if any)
GRANT SELECT ON ALL TABLES IN SCHEMA mercury TO mercury_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA mercury TO mercury_readwrite;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA mercury TO mercury_readonly;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA mercury TO mercury_readwrite;

-- Future objects created by flyway_user
ALTER DEFAULT PRIVILEGES FOR ROLE flyway_user IN SCHEMA mercury
  GRANT SELECT ON TABLES TO mercury_readonly;

ALTER DEFAULT PRIVILEGES FOR ROLE flyway_user IN SCHEMA mercury
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mercury_readwrite;

ALTER DEFAULT PRIVILEGES FOR ROLE flyway_user IN SCHEMA mercury
  GRANT USAGE, SELECT ON SEQUENCES TO mercury_readonly;

ALTER DEFAULT PRIVILEGES FOR ROLE flyway_user IN SCHEMA mercury
  GRANT USAGE, SELECT ON SEQUENCES TO mercury_readwrite;

-- ------------------------------------------------------------------------------------
-- 5) NICE: default search_path for these roles
-- ------------------------------------------------------------------------------------
ALTER ROLE flyway_user IN DATABASE mercury SET search_path = mercury, public;
ALTER ROLE catalog_service IN DATABASE mercury SET search_path = mercury, public;
ALTER ROLE order_service IN DATABASE mercury SET search_path = mercury, public;
ALTER ROLE admin IN DATABASE mercury SET search_path = mercury, public;