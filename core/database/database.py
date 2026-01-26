from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session
from config.config import Config
from .models import Base

# Create engine with connection pooling (optimized for high concurrency)
engine = create_engine(
    Config.SQLALCHEMY_DATABASE_URI,
    pool_size=25,
    max_overflow=50,
    pool_pre_ping=True,
    pool_recycle=3600,  # Recycle connections after 1 hour
    pool_timeout=30,  # Timeout for getting connection from pool
    echo=False
)

# Create session factory
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

def get_db():
    """Get database session (generator for dependency injection)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_db_session():
    """Get a database session directly (for use in routes)"""
    return SessionLocal()

def setup_database():
    """
    Initialize database tables and run migrations.
    This is safe to call on every startup - it only creates what doesn't exist.
    """
    init_db()


def init_db():
    """Initialize database - create all tables and apply lightweight migrations."""
    _migrate_legacy_subdomains_to_unique_schema()
    Base.metadata.create_all(bind=engine)
    _migrate_legacy_subdomains_data()
    _ensure_subdomains_columns()
    _add_performance_indexes()
    _enable_fulltext_search()
    print("Database tables created successfully")


def _migrate_legacy_subdomains_to_unique_schema():
    """
    One-time migration:
    - Old schema stored subdomains per scan in a `subdomains` table (with a `scan_id` column).
    - New schema stores globally unique subdomains in `subdomains` and links scans via `scan_subdomains`.

    This step renames the old table to `scan_subdomains_legacy` BEFORE SQLAlchemy create_all()
    so the new `subdomains` table can be created.
    """
    try:
        # Use engine.begin() so changes are committed automatically (SQLAlchemy 2.x)
        with engine.begin() as conn:
            # If new schema is already present, do nothing.
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
                # Already new-ish (or custom) schema; leave it alone.
                return

            # Rename old per-scan table out of the way.
            conn.execute(text("ALTER TABLE subdomains RENAME TO scan_subdomains_legacy;"))
    except Exception as e:
        print(f"Warning: legacy subdomains schema migration step failed: {e}")


def _migrate_legacy_subdomains_data():
    """
    If we detected a legacy `scan_subdomains_legacy` table, copy its data into:
    - `subdomains` (global unique subdomains)
    - `scan_subdomains` (per-scan links)

    We keep the legacy table as a backup.
    """
    try:
        # Use engine.begin() so changes are committed automatically (SQLAlchemy 2.x)
        with engine.begin() as conn:
            legacy_exists = conn.execute(
                text("SELECT to_regclass('public.scan_subdomains_legacy') IS NOT NULL")
            ).scalar()
            if not legacy_exists:
                return

            # If the new tables don't exist yet, create_all() hasn't run successfully.
            new_subdomains_exists = conn.execute(
                text("SELECT to_regclass('public.subdomains') IS NOT NULL")
            ).scalar()
            new_links_exists = conn.execute(
                text("SELECT to_regclass('public.scan_subdomains') IS NOT NULL")
            ).scalar()
            if not new_subdomains_exists or not new_links_exists:
                return

            # 1) Insert unique subdomains (one row per name), taking latest metadata and min/max timestamps.
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

            # 2) Insert per-scan links (scan_id <-> subdomain_id), preserving per-scan discovered_at.
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

            # 3) Recompute scan subdomain_count based on links.
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


def _ensure_subdomains_columns():
    """
    Ensure the `subdomains` table has the newer optional columns.

    SQLAlchemy `create_all()` does NOT modify existing tables, so older databases
    need a one-time ALTER TABLE. This is safe to run on every startup because we
    use `ADD COLUMN IF NOT EXISTS`.
    """
    migration_sql = """
        ALTER TABLE subdomains
        ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMP,
        ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP,
        ADD COLUMN IF NOT EXISTS size INTEGER,
        ADD COLUMN IF NOT EXISTS status_code INTEGER,
        ADD COLUMN IF NOT EXISTS headers TEXT,
        ADD COLUMN IF NOT EXISTS canonical_names TEXT,
        ADD COLUMN IF NOT EXISTS is_virtual_host VARCHAR(10) DEFAULT 'false',
        ADD COLUMN IF NOT EXISTS uri VARCHAR(500),
        ADD COLUMN IF NOT EXISTS is_online VARCHAR(50),
        ADD COLUMN IF NOT EXISTS probe_http_status INTEGER,
        ADD COLUMN IF NOT EXISTS probe_https_status INTEGER;
        
        ALTER TABLE scan_subdomains
        ADD COLUMN IF NOT EXISTS tool_name VARCHAR(100);
    """
    try:
        # Use engine.begin() so changes are committed automatically (SQLAlchemy 2.x)
        with engine.begin() as conn:
            conn.execute(text(migration_sql))
    except Exception as e:
        # Don't block app startup for brand new installs / misconfigured DBs;
        # routes will surface DB connectivity errors more explicitly.
        print(f"Warning: could not ensure subdomains columns: {e}")

def _add_performance_indexes():
    """
    Add performance indexes to existing database.
    Uses IF NOT EXISTS to be safe for existing databases.
    """
    indexes_sql = [
        # Project indexes
        "CREATE INDEX IF NOT EXISTS idx_project_created_at ON projects(created_at)",
        
        # Scan indexes
        "CREATE INDEX IF NOT EXISTS idx_scan_project_id ON scans(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_scan_target_domain ON scans(target_domain)",
        "CREATE INDEX IF NOT EXISTS idx_scan_status ON scans(status)",
        "CREATE INDEX IF NOT EXISTS idx_scan_started_at ON scans(started_at)",
        "CREATE INDEX IF NOT EXISTS idx_scan_completed_at ON scans(completed_at)",
        "CREATE INDEX IF NOT EXISTS idx_scan_project_target ON scans(project_id, target_domain)",
        "CREATE INDEX IF NOT EXISTS idx_scan_target_status ON scans(target_domain, status)",
        
        # Subdomain indexes
        "CREATE INDEX IF NOT EXISTS idx_subdomain_target ON subdomains(target_domain)",
        "CREATE INDEX IF NOT EXISTS idx_subdomain_last_seen ON subdomains(last_seen_at)",
        "CREATE INDEX IF NOT EXISTS idx_subdomain_first_seen ON subdomains(first_seen_at)",
        
        # ScanSubdomain indexes
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
                    # Log but don't fail - some indexes might already exist or have different names
                    print(f"Warning: Could not create index: {e}")
    except Exception as e:
        print(f"Warning: Could not add performance indexes: {e}")


def _enable_fulltext_search():
    """
    Enable PostgreSQL extensions and create full-text search indexes.
    Requires pg_trgm extension for trigram-based text search.
    """
    try:
        with engine.begin() as conn:
            # Enable pg_trgm extension for trigram-based text search
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            
            # Create GIN indexes for full-text search on subdomain
            # These indexes will make ILIKE queries much faster
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


def run_maintenance():
    """
    Run database maintenance tasks (VACUUM ANALYZE).
    Should be called periodically (e.g., via cron or scheduled task).
    """
    try:
        with engine.begin() as conn:
            # VACUUM ANALYZE updates table statistics and reclaims space
            conn.execute(text("VACUUM ANALYZE"))
            print("Database maintenance completed successfully")
            return True
    except Exception as e:
        print(f"Error running database maintenance: {e}")
        return False


def get_database_stats():
    """
    Get database statistics including table sizes and index usage.
    Returns a dictionary with statistics.
    """
    stats = {}
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
            stats['table_sizes'] = [
                {
                    'table': row[1],
                    'size': row[2],
                    'size_bytes': row[3]
                }
                for row in table_sizes
            ]
            
            # Get index usage statistics
            index_stats = conn.execute(text("""
                SELECT 
                    schemaname,
                    tablename,
                    indexname,
                    idx_scan as index_scans,
                    idx_tup_read as tuples_read,
                    idx_tup_fetch as tuples_fetched
                FROM pg_stat_user_indexes
                WHERE schemaname = 'public'
                ORDER BY idx_scan DESC
                LIMIT 20
            """))
            stats['index_usage'] = [
                {
                    'table': row[1],
                    'index': row[2],
                    'scans': row[3],
                    'tuples_read': row[4],
                    'tuples_fetched': row[5]
                }
                for row in index_stats
            ]
            
            # Get connection pool info
            pool_info = conn.execute(text("""
                SELECT 
                    count(*) as total_connections,
                    count(*) FILTER (WHERE state = 'active') as active_connections,
                    count(*) FILTER (WHERE state = 'idle') as idle_connections
                FROM pg_stat_activity
                WHERE datname = current_database()
            """))
            pool_row = pool_info.fetchone()
            stats['connections'] = {
                'total': pool_row[0] if pool_row else 0,
                'active': pool_row[1] if pool_row else 0,
                'idle': pool_row[2] if pool_row else 0
            }
            
            # Get row counts for main tables
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
            stats['row_counts'] = {
                row[0]: row[1] for row in row_counts
            }
            
    except Exception as e:
        print(f"Error getting database stats: {e}")
        stats['error'] = str(e)
    
    return stats


def drop_db():
    """Drop all database tables"""
    Base.metadata.drop_all(bind=engine)
    print("Database tables dropped successfully")

