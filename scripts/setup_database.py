#!/usr/bin/env python3
"""
Database Setup Script for BellowTheRoot

This script initializes the PostgreSQL database by:
1. Checking database connectivity
2. Creating all required tables
3. Running migrations
4. Setting up indexes and extensions
5. Verifying the setup

Usage:
    python3 scripts/setup_database.py
    or
    ./scripts/setup_database.py
"""

import sys
import os
import getpass
from pathlib import Path
from urllib.parse import urlparse

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import OperationalError, ProgrammingError
from core.database import Base
from core.database.database import init_db, get_database_stats


def print_header(text):
    """Print a formatted header"""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60 + "\n")


def print_success(text):
    """Print success message"""
    print(f"✓ {text}")


def print_error(text):
    """Print error message"""
    print(f"✗ {text}", file=sys.stderr)


def print_info(text):
    """Print info message"""
    print(f"ℹ {text}")


def get_database_credentials():
    """Prompt user for database credentials"""
    print_header("Database Configuration")
    
    # Check if .env file exists and ask if user wants to use it
    env_file = project_root / '.env'
    use_env = False
    
    if env_file.exists():
        # Load .env to check what DATABASE_URL is set to
        from dotenv import load_dotenv
        load_dotenv(env_file)
        db_url_from_env = os.getenv('DATABASE_URL', '')
        
        if db_url_from_env:
            # Parse and display database info (without password)
            try:
                parsed = urlparse(db_url_from_env)
                db_user = parsed.username or 'N/A'
                db_host = parsed.hostname or 'N/A'
                db_port = parsed.port or '5432'
                db_name = parsed.path.lstrip('/') if parsed.path else 'N/A'
                
                print_info("Found .env file with database configuration.")
                print_info(f"Database: {db_name}")
                print_info(f"Host: {db_host}:{db_port}")
                print_info(f"User: {db_user}")
                print_info("Password: [hidden]")
            except Exception:
                print_info("Found .env file with DATABASE_URL configured.")
            
            response = input("\nUse credentials from .env file? [Y/n]: ").strip().lower()
            if response in ('', 'y', 'yes'):
                use_env = True
                print_info("Using credentials from .env file")
                print()
                return None  # Return None to indicate using default engine
        else:
            print_info("Found .env file but DATABASE_URL is not set.")
            print_info("You'll need to enter credentials manually.")
            print()
    
    if not use_env:
        print("Please enter your database credentials:")
        print("(Press Enter to use defaults shown in brackets)")
        print()
        
        db_host = input("Database host [localhost]: ").strip() or "localhost"
        db_port = input("Database port [5432]: ").strip() or "5432"
        db_name = input("Database name [subdomain_enum]: ").strip() or "subdomain_enum"
        db_user = input("Database user [postgres]: ").strip() or "postgres"
        db_password = getpass.getpass("Database password: ").strip()
        
        if not db_password:
            print_error("Password cannot be empty")
            return None
        
        # Build database URL
        db_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        return db_url
    
    return None


def check_database_connection(engine):
    """Check if we can connect to the database"""
    print_header("Checking Database Connection")
    
    try:
        # Try to connect
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print_success(f"Connected to database")
            print_info(f"PostgreSQL version: {version.split(',')[0]}")
            return True
    except OperationalError as e:
        print_error(f"Failed to connect to database: {e}")
        # Get database info from engine URL (without password)
        db_url = str(engine.url)
        if '@' in db_url:
            db_info = db_url.split('@')[-1]
        else:
            db_info = "hidden"
        print_info(f"Database: {db_info}")
        print("\nPlease check:")
        print("  1. PostgreSQL is running")
        print("  2. Database credentials are correct")
        print("  3. Database exists (if not, create it first)")
        return False
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        return False


def check_database_exists(engine):
    """Check if the database exists"""
    print_header("Checking Database Existence")
    
    try:
        # Extract database name from engine URL
        db_url = engine.url
        db_name = db_url.database
        
        # Connect to postgres database to check if our database exists
        # Create a new URL string with 'postgres' as the database
        db_url_str = str(db_url)
        postgres_url_str = db_url_str.rsplit('/', 1)[0] + '/postgres'
        postgres_engine = create_engine(postgres_url_str)
        
        with postgres_engine.connect() as conn:
            result = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :db_name"),
                {"db_name": db_name}
            )
            exists = result.fetchone() is not None
            
            if exists:
                print_success(f"Database '{db_name}' exists")
            else:
                print_error(f"Database '{db_name}' does not exist")
                print_info("You may need to create it first using:")
                print_info(f"  createdb -U {db_url.username} {db_name}")
                print_info("Or use the bash script: scripts/setup_database.sh")
            
            return exists
    except Exception as e:
        print_info(f"Could not check database existence: {e}")
        print_info("Assuming database exists and continuing...")
        return True


def list_existing_tables(engine):
    """List existing tables in the database"""
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        if tables:
            print_info(f"Existing tables: {', '.join(tables)}")
            return tables
        else:
            print_info("No tables found in database")
            return []
    except Exception as e:
        print_error(f"Could not list tables: {e}")
        return []


def initialize_database(engine):
    """Initialize database tables and run migrations"""
    print_header("Initializing Database Tables")
    
    try:
        # List existing tables before initialization
        existing_tables = list_existing_tables(engine)
        
        # Initialize database (creates tables, runs migrations, sets up indexes)
        # We need to use the custom engine, so we'll call the internal functions
        print_info("Creating tables and running migrations...")
        
        # Import the internal migration functions
        from core.database.database import (
            _migrate_legacy_subdomains_to_unique_schema,
            _migrate_legacy_subdomains_data,
            _ensure_subdomains_columns,
            _add_performance_indexes,
            _enable_fulltext_search
        )
        
        # Run migrations with custom engine
        _migrate_legacy_subdomains_to_unique_schema_custom(engine)
        Base.metadata.create_all(bind=engine)
        _migrate_legacy_subdomains_data_custom(engine)
        _ensure_subdomains_columns_custom(engine)
        _add_performance_indexes_custom(engine)
        _enable_fulltext_search_custom(engine)
        
        print("Database tables created successfully")
        
        # List tables after initialization
        new_tables = list_existing_tables(engine)
        
        if new_tables:
            print_success(f"Database initialized successfully")
            print_info(f"Total tables: {len(new_tables)}")
        else:
            print_error("No tables were created")
            return False
        
        return True
    except Exception as e:
        print_error(f"Failed to initialize database: {e}")
        import traceback
        traceback.print_exc()
        return False


def _migrate_legacy_subdomains_to_unique_schema_custom(engine):
    """Custom version that uses provided engine"""
    try:
        with engine.begin() as conn:
            scan_subdomains_exists = conn.execute(
                text("SELECT to_regclass('public.scan_subdomains') IS NOT NULL")
            ).scalar()
            if scan_subdomains_exists:
                return

            legacy_exists = conn.execute(
                text("SELECT to_regclass('public.scan_subdomains_legacy') IS NOT NULL")
            ).scalar()
            if legacy_exists:
                return

            old_subdomains_exists = conn.execute(
                text("SELECT to_regclass('public.subdomains') IS NOT NULL")
            ).scalar()
            if not old_subdomains_exists:
                return

            old_has_scan_id = conn.execute(
                text("""
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'subdomains'
                          AND column_name = 'scan_id'
                    )
                """)
            ).scalar()
            if not old_has_scan_id:
                return

            conn.execute(text("ALTER TABLE subdomains RENAME TO scan_subdomains_legacy;"))
    except Exception as e:
        print(f"Warning: legacy subdomains schema migration step failed: {e}")


def _migrate_legacy_subdomains_data_custom(engine):
    """Custom version that uses provided engine"""
    try:
        with engine.begin() as conn:
            legacy_exists = conn.execute(
                text("SELECT to_regclass('public.scan_subdomains_legacy') IS NOT NULL")
            ).scalar()
            if not legacy_exists:
                return

            new_subdomains_exists = conn.execute(
                text("SELECT to_regclass('public.subdomains') IS NOT NULL")
            ).scalar()
            new_links_exists = conn.execute(
                text("SELECT to_regclass('public.scan_subdomains') IS NOT NULL")
            ).scalar()
            if not new_subdomains_exists or not new_links_exists:
                return

            conn.execute(text("""
                WITH bounds AS (
                    SELECT
                        subdomain,
                        MAX(target_domain) AS target_domain,
                        MIN(discovered_at) AS first_seen_at,
                        MAX(discovered_at) AS last_seen_at
                    FROM scan_subdomains_legacy
                    GROUP BY subdomain
                ),
                latest AS (
                    SELECT DISTINCT ON (subdomain)
                        subdomain,
                        size,
                        status_code,
                        headers,
                        canonical_names,
                        is_virtual_host,
                        uri
                    FROM scan_subdomains_legacy
                    ORDER BY subdomain, discovered_at DESC NULLS LAST
                )
                INSERT INTO subdomains (
                    subdomain,
                    target_domain,
                    first_seen_at,
                    last_seen_at,
                    size,
                    status_code,
                    headers,
                    canonical_names,
                    is_virtual_host,
                    uri
                )
                SELECT
                    b.subdomain,
                    b.target_domain,
                    COALESCE(b.first_seen_at, now() AT TIME ZONE 'utc'),
                    COALESCE(b.last_seen_at, now() AT TIME ZONE 'utc'),
                    l.size,
                    l.status_code,
                    l.headers,
                    l.canonical_names,
                    l.is_virtual_host,
                    l.uri
                FROM bounds b
                LEFT JOIN latest l USING (subdomain)
                ON CONFLICT (subdomain) DO NOTHING;
            """))

            conn.execute(text("""
                INSERT INTO scan_subdomains (scan_id, subdomain_id, discovered_at)
                SELECT
                    l.scan_id,
                    s.id AS subdomain_id,
                    l.discovered_at
                FROM scan_subdomains_legacy l
                JOIN subdomains s
                  ON s.subdomain = l.subdomain
                ON CONFLICT (scan_id, subdomain_id) DO NOTHING;
            """))

            conn.execute(text("""
                UPDATE scans
                SET subdomain_count = COALESCE(x.cnt, 0)
                FROM (
                    SELECT scan_id, COUNT(*) AS cnt
                    FROM scan_subdomains
                    GROUP BY scan_id
                ) x
                WHERE scans.id = x.scan_id;
            """))
    except Exception as e:
        print(f"Warning: legacy subdomains data migration failed: {e}")


def _ensure_subdomains_columns_custom(engine):
    """Custom version that uses provided engine"""
    migration_sql = """
        ALTER TABLE subdomains
        ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMP,
        ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP,
        ADD COLUMN IF NOT EXISTS size INTEGER,
        ADD COLUMN IF NOT EXISTS status_code INTEGER,
        ADD COLUMN IF NOT EXISTS headers TEXT,
        ADD COLUMN IF NOT EXISTS canonical_names TEXT,
        ADD COLUMN IF NOT EXISTS is_virtual_host VARCHAR(10) DEFAULT 'false',
        ADD COLUMN IF NOT EXISTS uri VARCHAR(500);
        
        ALTER TABLE scan_subdomains
        ADD COLUMN IF NOT EXISTS tool_name VARCHAR(100);
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(migration_sql))
    except Exception as e:
        print(f"Warning: could not ensure subdomains columns: {e}")


def _add_performance_indexes_custom(engine):
    """Custom version that uses provided engine"""
    indexes_sql = [
        "CREATE INDEX IF NOT EXISTS idx_project_created_at ON projects(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_scan_project_id ON scans(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_scan_target_domain ON scans(target_domain)",
        "CREATE INDEX IF NOT EXISTS idx_scan_status ON scans(status)",
        "CREATE INDEX IF NOT EXISTS idx_scan_started_at ON scans(started_at)",
        "CREATE INDEX IF NOT EXISTS idx_scan_completed_at ON scans(completed_at)",
        "CREATE INDEX IF NOT EXISTS idx_scan_project_target ON scans(project_id, target_domain)",
        "CREATE INDEX IF NOT EXISTS idx_scan_target_status ON scans(target_domain, status)",
        "CREATE INDEX IF NOT EXISTS idx_subdomain_target ON subdomains(target_domain)",
        "CREATE INDEX IF NOT EXISTS idx_subdomain_last_seen ON subdomains(last_seen_at)",
        "CREATE INDEX IF NOT EXISTS idx_subdomain_first_seen ON subdomains(first_seen_at)",
        "CREATE INDEX IF NOT EXISTS idx_scan_subdomain_scan ON scan_subdomains(scan_id)",
        "CREATE INDEX IF NOT EXISTS idx_scan_subdomain_subdomain ON scan_subdomains(subdomain_id)",
        "CREATE INDEX IF NOT EXISTS idx_scan_subdomain_discovered ON scan_subdomains(discovered_at)",
        "CREATE INDEX IF NOT EXISTS idx_scan_subdomain_scan_discovered ON scan_subdomains(scan_id, discovered_at)",
    ]
    
    try:
        with engine.begin() as conn:
            for sql in indexes_sql:
                try:
                    conn.execute(text(sql))
                except Exception as e:
                    print(f"Warning: Could not create index: {e}")
    except Exception as e:
        print(f"Warning: Could not add performance indexes: {e}")


def _enable_fulltext_search_custom(engine):
    """Custom version that uses provided engine"""
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            
            fulltext_indexes = [
                "CREATE INDEX IF NOT EXISTS idx_subdomain_fts_subdomain ON subdomains USING gin(subdomain gin_trgm_ops)",
            ]
            
            for sql in fulltext_indexes:
                try:
                    conn.execute(text(sql))
                except Exception as e:
                    print(f"Warning: Could not create full-text search index: {e}")
    except Exception as e:
        print(f"Warning: Could not enable full-text search: {e}")


def verify_setup(engine):
    """Verify that all required tables exist"""
    print_header("Verifying Database Setup")
    
    required_tables = ['projects', 'scans', 'subdomains', 'scan_subdomains', 'settings']
    missing_tables = []
    
    try:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        
        for table in required_tables:
            if table in existing_tables:
                # Get row count
                with engine.connect() as conn:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = result.scalar()
                print_success(f"Table '{table}' exists ({count} rows)")
            else:
                print_error(f"Table '{table}' is missing")
                missing_tables.append(table)
        
        if missing_tables:
            print_error(f"Missing tables: {', '.join(missing_tables)}")
            return False
        else:
            print_success("All required tables exist")
            return True
    except Exception as e:
        print_error(f"Failed to verify setup: {e}")
        return False


def check_extensions(engine):
    """Check if required PostgreSQL extensions are installed"""
    print_header("Checking PostgreSQL Extensions")
    
    try:
        with engine.connect() as conn:
            # Check for pg_trgm extension (used for full-text search)
            result = conn.execute(
                text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")
            )
            pg_trgm_exists = result.scalar()
            
            if pg_trgm_exists:
                print_success("pg_trgm extension is installed")
            else:
                print_info("pg_trgm extension is not installed (optional, used for full-text search)")
        
        return True
    except Exception as e:
        print_info(f"Could not check extensions: {e}")
        return True  # Don't fail on this


def show_database_stats(engine):
    """Show database statistics"""
    print_header("Database Statistics")
    
    try:
        with engine.connect() as conn:
            # Get table sizes
            table_sizes = conn.execute(text("""
                SELECT 
                    schemaname,
                    tablename,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
                    pg_total_relation_size(schemaname||'.'||tablename) AS size_bytes
                FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
            """))
            
            # Get row counts
            row_counts = conn.execute(text("""
                SELECT 
                    'projects' as table_name, COUNT(*) as count FROM projects
                UNION ALL
                SELECT 'scans', COUNT(*) FROM scans
                UNION ALL
                SELECT 'subdomains', COUNT(*) FROM subdomains
                UNION ALL
                SELECT 'scan_subdomains', COUNT(*) FROM scan_subdomains
            """))
            
            # Show row counts
            print_info("Row counts:")
            for row in row_counts:
                print(f"  {row[0]}: {row[1]}")
            
            # Show table sizes
            sizes = list(table_sizes)
            if sizes:
                print_info("\nTable sizes:")
                for row in sizes:
                    print(f"  {row[1]}: {row[2]}")
        
    except Exception as e:
        print_info(f"Could not get database stats: {e}")


def main():
    """Main setup function"""
    print_header("BellowTheRoot Database Setup")
    
    # Get database credentials from user
    db_url = get_database_credentials()
    
    # Create engine with user-provided credentials or use default
    if db_url:
        # User provided custom credentials
        engine = create_engine(
            db_url,
            pool_size=25,
            max_overflow=50,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_timeout=30,
            echo=False
        )
    else:
        # Use default engine from config
        from core.database.database import engine as default_engine
        engine = default_engine
    
    # Step 1: Check database connection
    if not check_database_connection(engine):
        print("\n" + "=" * 60)
        print("Setup failed: Cannot connect to database")
        print("=" * 60)
        sys.exit(1)
    
    # Step 2: Check if database exists (optional check)
    check_database_exists(engine)
    
    # Step 3: Initialize database
    if not initialize_database(engine):
        print("\n" + "=" * 60)
        print("Setup failed: Could not initialize database")
        print("=" * 60)
        sys.exit(1)
    
    # Step 4: Verify setup
    if not verify_setup(engine):
        print("\n" + "=" * 60)
        print("Setup failed: Verification failed")
        print("=" * 60)
        sys.exit(1)
    
    # Step 5: Check extensions
    check_extensions(engine)
    
    # Step 6: Show statistics
    show_database_stats(engine)
    
    # Success message
    print("\n" + "=" * 60)
    print("  Database setup completed successfully!")
    print("=" * 60)
    print("\nYou can now start the application with:")
    print("  python3 app.py")
    print()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSetup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
