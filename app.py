from flask import Flask, render_template, jsonify, request, Response, stream_with_context
from flask_cors import CORS
from core.database import get_db_session, setup_database, get_database_stats, run_maintenance
from core.database import Project, Scan, Subdomain, ScanSubdomain, Setting
from core.scan_orchestrator import start_orchestrated_scan
from tool_executor import load_tools_config, save_tools_config, get_tool_config, get_enabled_tools, get_pipeline_tools
from tool_executor.common import format_args_for_display
from core.terminal_output import get_output
from core.scan_control import request_stop
from datetime import datetime, timezone
from sqlalchemy import func, text, or_
from sqlalchemy.orm import selectinload, joinedload
import json
import time
import yaml

app = Flask(__name__)
app.config.from_object('config.config.Config')
CORS(app)

# Set up database on startup (creates database and tables if first run)
with app.app_context():
    setup_database()

def _build_fulltext_search_filter(db, search_term, columns):
    """
    Build full-text search filter using PostgreSQL trigram similarity.
    Falls back to ILIKE if pg_trgm extension is not available.
    
    Args:
        db: Database session
        search_term: Search term
        columns: List of column objects to search in
    
    Returns:
        SQLAlchemy filter expression
    """
    try:
        # Check if pg_trgm extension is available
        has_extension = db.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")
        ).scalar()
        
        if has_extension:
            # Use trigram similarity for faster text search
            # Similarity threshold of 0.3 provides good balance
            filters = []
            for col in columns:
                filters.append(
                    func.similarity(col, search_term) > 0.3
                )
            return or_(*filters)
        else:
            # Fallback to ILIKE
            filters = []
            for col in columns:
                filters.append(col.ilike(f'%{search_term}%'))
            return or_(*filters)
    except Exception:
        # Fallback to ILIKE on any error
        filters = []
        for col in columns:
            filters.append(col.ilike(f'%{search_term}%'))
        return or_(*filters)


def _paginate_cursor(query, cursor_field, cursor_value, limit, order_desc=True):
    """
    Cursor-based pagination helper.
    Returns results, next_cursor, and has_more flag.
    
    Args:
        query: SQLAlchemy query
        cursor_field: Field to use as cursor (must be unique or part of unique constraint)
        cursor_value: Current cursor value (None for first page)
        limit: Number of results to return
        order_desc: If True, order descending (for "newest first")
    
    Returns:
        tuple: (results, next_cursor, has_more)
    """
    if cursor_value:
        if order_desc:
            query = query.filter(cursor_field < cursor_value)
        else:
            query = query.filter(cursor_field > cursor_value)
    
    query = query.order_by(cursor_field.desc() if order_desc else cursor_field.asc())
    results = query.limit(limit + 1).all()  # Fetch one extra to check if more exists
    
    has_more = len(results) > limit
    if has_more:
        results = results[:-1]
    
    next_cursor = results[-1].id if results and has_more else None
    return results, next_cursor, has_more

@app.route('/')
def index():
    """Serve main HTML page"""
    return render_template('index.html')

# Project endpoints
@app.route('/api/projects', methods=['GET'])
def get_projects():
    """List all projects with aggregated statistics"""
    db = get_db_session()
    try:
        # Use selectinload to prevent N+1 queries when accessing project.scans
        projects = db.query(Project).options(selectinload(Project.scans)).order_by(Project.created_at.desc()).all()
        result = []
        for project in projects:
            project_dict = project.to_dict()
            
            # Get scan IDs for this project (already loaded via selectinload)
            scan_ids = [scan.id for scan in project.scans]
            
            # Count unique target domains (optimized query)
            target_count = 0
            if scan_ids:
                target_count = db.query(func.count(func.distinct(Scan.target_domain))).filter(
                    Scan.id.in_(scan_ids)
                ).scalar() or 0
            
            # Count unique subdomains across all scans (optimized query)
            subdomain_count = 0
            if scan_ids:
                subdomain_count = db.query(func.count(func.distinct(Subdomain.id))).join(
                    ScanSubdomain, Subdomain.id == ScanSubdomain.subdomain_id
                ).filter(
                    ScanSubdomain.scan_id.in_(scan_ids)
                ).scalar() or 0
            
            project_dict['target_count'] = target_count
            project_dict['subdomain_count'] = subdomain_count
            result.append(project_dict)
        
        return jsonify(result)
    finally:
        db.close()

@app.route('/api/projects', methods=['POST'])
def create_project():
    """Create a new project"""
    data = request.get_json()
    
    if not data or 'name' not in data:
        return jsonify({'error': 'Project name is required'}), 400
    
    db = get_db_session()
    try:
        # Check if project name already exists
        existing = db.query(Project).filter(Project.name == data['name']).first()
        if existing:
            return jsonify({'error': 'Project with this name already exists'}), 400
        
        project = Project(
            name=data['name'],
            description=data.get('description', '')
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        
        return jsonify(project.to_dict()), 201
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/projects/<int:project_id>', methods=['GET'])
def get_project(project_id):
    """Get project details with scans"""
    db = get_db_session()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        project_dict = project.to_dict()
        project_dict['scans'] = [scan.to_dict() for scan in project.scans]
        
        return jsonify(project_dict)
    finally:
        db.close()

@app.route('/api/projects/<int:project_id>/subdomains', methods=['GET'])
def get_project_subdomains(project_id):
    """Get all unique subdomains for a project across all its scans with pagination"""
    db = get_db_session()
    try:
        # Pagination parameters - support both cursor and offset-based
        cursor = request.args.get('cursor', type=int)
        page = request.args.get('page', type=int)
        limit = request.args.get('limit', 100, type=int)
        search = request.args.get('search', '', type=str).strip()
        target_filter = request.args.get('target', '', type=str)
        
        # Cap limit to prevent abuse (allow up to 5000)
        limit = min(limit, 5000)
        
        # Use cursor-based pagination if cursor is provided, otherwise use offset
        use_cursor = cursor is not None
        if not use_cursor and page:
            offset = (page - 1) * limit
        else:
            offset = None
        
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        # Get all scan IDs for this project
        scan_ids = [scan.id for scan in project.scans]
        
        if not scan_ids:
            return jsonify({
                'targets': [],
                'subdomains': [],
                'pagination': {'page': 1, 'limit': limit, 'total': 0, 'pages': 0}
            })
        
        # Get targets (unique domains) with UNIQUE subdomain counts
        targets = []
        target_domains = {}
        
        # Group scans by target domain
        for scan in project.scans:
            if scan.target_domain not in target_domains:
                target_domains[scan.target_domain] = {
                    'scan_ids': [],
                    'status': scan.status
                }
            target_domains[scan.target_domain]['scan_ids'].append(scan.id)
        
        # Count unique subdomains per target domain
        for domain, info in target_domains.items():
            # Get unique subdomain count for all scans of this target
            unique_count = db.query(func.count(func.distinct(Subdomain.subdomain))).join(
                ScanSubdomain, Subdomain.id == ScanSubdomain.subdomain_id
            ).filter(
                ScanSubdomain.scan_id.in_(info['scan_ids'])
            ).scalar() or 0
            
            targets.append({
                'domain': domain,
                'subdomain_count': unique_count,
                'scan_ids': info['scan_ids'],
                'status': info['status']
            })
        
        # Build optimized query for unique subdomains with pagination
        # Use a subquery to get the latest discovery for each unique subdomain
        latest_per_subdomain = db.query(
            ScanSubdomain.subdomain_id,
            func.max(ScanSubdomain.discovered_at).label('latest_discovered')
        ).join(Scan).filter(
            Scan.project_id == project_id
        ).group_by(ScanSubdomain.subdomain_id).subquery()
        
        # Base query for paginated subdomains
        base_query = db.query(Subdomain, Scan.target_domain, ScanSubdomain.tool_name).join(
            latest_per_subdomain, latest_per_subdomain.c.subdomain_id == Subdomain.id
        ).join(
            ScanSubdomain,
            (ScanSubdomain.subdomain_id == Subdomain.id) &
            (ScanSubdomain.discovered_at == latest_per_subdomain.c.latest_discovered)
        ).join(Scan, ScanSubdomain.scan_id == Scan.id)
        
        # Apply filters
        if search:
            # Use full-text search if available, fallback to ILIKE
            base_query = base_query.filter(
                _build_fulltext_search_filter(
                    db, search,
                    [Subdomain.subdomain]
                )
            )
        
        if target_filter:
            base_query = base_query.filter(Scan.target_domain == target_filter)
        
        # Get total count (only if using offset pagination)
        total = None
        if not use_cursor:
            total = base_query.distinct(Subdomain.id).count()
        
        # Get paginated results
        if use_cursor:
            # Cursor-based pagination - much faster for large datasets
            # Note: Uses Subdomain.id for cursor (instead of latest_discovered timestamp)
            # This provides consistent, fast pagination but ordering may differ slightly
            # from offset-based pagination which orders by latest_discovered
            if cursor:
                base_query = base_query.filter(Subdomain.id < cursor)
            
            base_query = base_query.order_by(Subdomain.id.desc())
            results = base_query.limit(limit + 1).all()
            
            has_more = len(results) > limit
            if has_more:
                results = results[:-1]
            
            next_cursor = results[-1][0].id if results and has_more else None
            
            subdomains_result = []
            for subdomain, target_domain, tool_name in results:
                subdomain_dict = subdomain.to_dict()
                subdomain_dict['target_domain'] = target_domain
                subdomain_dict['tool_name'] = tool_name
                subdomains_result.append(subdomain_dict)
            
            pagination = {
                'limit': limit,
                'cursor': next_cursor,
                'has_more': has_more
            }
        else:
            # Offset-based pagination (for backward compatibility)
            results = base_query.order_by(latest_per_subdomain.c.latest_discovered.desc()).offset(offset).limit(limit).all()
            
            subdomains_result = []
            for subdomain, target_domain, tool_name in results:
                subdomain_dict = subdomain.to_dict()
                subdomain_dict['target_domain'] = target_domain
                subdomain_dict['tool_name'] = tool_name
                subdomains_result.append(subdomain_dict)
            
            pagination = {
                'page': page or 1,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit if total else 0
            }
        
        return jsonify({
            'targets': targets,
            'subdomains': subdomains_result,
            'pagination': pagination
        })
    finally:
        db.close()

@app.route('/api/projects/<int:project_id>', methods=['DELETE'])
def delete_project(project_id):
    """Delete a project and all associated data including orphaned subdomains"""
    db = get_db_session()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        project_name = project.name
        
        # Get counts before deletion
        scan_ids = [scan.id for scan in project.scans]
        scan_count = len(scan_ids)
        
        # Get subdomain IDs linked to this project's scans
        subdomain_ids = []
        if scan_ids:
            subdomain_ids = [
                row[0] for row in db.query(ScanSubdomain.subdomain_id).filter(
                    ScanSubdomain.scan_id.in_(scan_ids)
                ).distinct().all()
            ]
        
        # Count scan_subdomains that will be deleted
        scan_subdomain_count = 0
        if scan_ids:
            scan_subdomain_count = db.query(ScanSubdomain).filter(
                ScanSubdomain.scan_id.in_(scan_ids)
            ).count()
        
        # IMPORTANT: legacy backup table may still reference scans via FK.
        # Clean it up first so scan deletion isn't blocked.
        if scan_ids:
            legacy_exists = db.execute(
                text("SELECT to_regclass('public.scan_subdomains_legacy') IS NOT NULL")
            ).scalar()
            if legacy_exists:
                db.execute(
                    text("DELETE FROM scan_subdomains_legacy WHERE scan_id = ANY(:scan_ids)"),
                    {'scan_ids': scan_ids}
                )
                db.commit()

        # Delete the project (cascade will handle scans and scan_subdomains)
        db.delete(project)
        db.commit()
        
        # Now delete orphaned subdomains (subdomains no longer referenced by any scan)
        subdomain_delete_count = 0
        if subdomain_ids:
            # Find subdomains that are no longer referenced by any scan
            orphaned_subdomains = db.query(Subdomain).filter(
                Subdomain.id.in_(subdomain_ids),
                ~Subdomain.id.in_(
                    db.query(ScanSubdomain.subdomain_id).distinct()
                )
            ).all()
            
            for subdomain in orphaned_subdomains:
                db.delete(subdomain)
                subdomain_delete_count += 1
            
            db.commit()
        
        return jsonify({
            'message': f'Project "{project_name}" deleted successfully',
            'deleted': {
                'project_id': project_id,
                'project_name': project_name,
                'scans': scan_count,
                'scan_subdomains': scan_subdomain_count,
                'subdomains': subdomain_delete_count
            }
        }), 200
    except Exception as e:
        db.rollback()
        print(f"Error deleting project: {str(e)}")
        return jsonify({'error': 'Failed to delete project', 'details': str(e)}), 500
    finally:
        db.close()

@app.route('/api/targets', methods=['GET'])
def get_all_targets():
    """Get all unique targets across all projects with subdomain counts"""
    db = get_db_session()
    try:
        # Get all unique target domains from scans
        target_domains = db.query(Scan.target_domain).distinct().all()
        
        if not target_domains:
            return jsonify({'targets': []}), 200
        
        targets = []
        for (target_domain,) in target_domains:
            # Get scans for this target
            scans = db.query(Scan).filter(Scan.target_domain == target_domain).all()
            scan_ids = [scan.id for scan in scans]
            project_ids = list(set([scan.project_id for scan in scans]))
            
            # Count unique subdomains for this target
            subdomain_count = 0
            if scan_ids:
                subdomain_count = db.query(func.count(func.distinct(Subdomain.id))).join(
                    ScanSubdomain, Subdomain.id == ScanSubdomain.subdomain_id
                ).filter(
                    ScanSubdomain.scan_id.in_(scan_ids)
                ).scalar() or 0
            
            targets.append({
                'domain': target_domain,
                'subdomain_count': subdomain_count,
                'scan_count': len(scan_ids),
                'project_count': len(project_ids)
            })
        
        # Sort by domain name
        targets.sort(key=lambda x: x['domain'])
        
        return jsonify({'targets': targets}), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/targets/<path:target_domain>/project', methods=['GET'])
def get_target_project(target_domain):
    """Get the project ID that should be used for a target domain (most recent scan)"""
    db = get_db_session()
    try:
        # Get the most recent scan for this target domain
        latest_scan = db.query(Scan).filter(
            Scan.target_domain == target_domain
        ).order_by(Scan.started_at.desc()).first()
        
        if latest_scan:
            return jsonify({'project_id': latest_scan.project_id}), 200
        
        # If no scans exist for this target, return the first available project
        first_project = db.query(Project).order_by(Project.created_at.desc()).first()
        if first_project:
            return jsonify({'project_id': first_project.id}), 200
        
        return jsonify({'error': 'No projects available'}), 404
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/targets/<path:target_domain>', methods=['DELETE'])
def delete_target(target_domain):
    """Delete a target domain and all related subdomains, scans, and scan_subdomains"""
    db = get_db_session()
    try:
        # URL decode the target domain
        from urllib.parse import unquote
        target_domain = unquote(target_domain)
        
        # Find all scans for this target domain
        scans = db.query(Scan).filter(Scan.target_domain == target_domain).all()
        
        if not scans:
            return jsonify({'error': 'Target not found'}), 404
        
        scan_ids = [scan.id for scan in scans]
        project_ids = list(set([scan.project_id for scan in scans]))
        
        # Get subdomain IDs linked to these scans
        subdomain_ids = []
        if scan_ids:
            subdomain_ids = [
                row[0] for row in db.query(ScanSubdomain.subdomain_id).filter(
                    ScanSubdomain.scan_id.in_(scan_ids)
                ).distinct().all()
            ]
        
        # Count what will be deleted
        scan_count = len(scan_ids)
        scan_subdomain_count = 0
        if scan_ids:
            scan_subdomain_count = db.query(ScanSubdomain).filter(
                ScanSubdomain.scan_id.in_(scan_ids)
            ).count()
        
        # Delete scan_subdomains (cascade should handle this, but be explicit)
        if scan_ids:
            db.query(ScanSubdomain).filter(ScanSubdomain.scan_id.in_(scan_ids)).delete(synchronize_session=False)
            db.commit()
        
        # Delete scans
        for scan in scans:
            db.delete(scan)
        db.commit()
        
        # Delete orphaned subdomains (subdomains no longer referenced by any scan)
        subdomain_delete_count = 0
        if subdomain_ids:
            # Find subdomains that are no longer referenced by any scan
            orphaned_subdomains = db.query(Subdomain).filter(
                Subdomain.id.in_(subdomain_ids),
                ~Subdomain.id.in_(
                    db.query(ScanSubdomain.subdomain_id).distinct()
                )
            ).all()
            
            for subdomain in orphaned_subdomains:
                db.delete(subdomain)
                subdomain_delete_count += 1
            
            db.commit()
        
        return jsonify({
            'message': f'Target "{target_domain}" deleted successfully',
            'deleted': {
                'target_domain': target_domain,
                'scans': scan_count,
                'scan_subdomains': scan_subdomain_count,
                'subdomains': subdomain_delete_count,
                'projects_affected': len(project_ids)
            }
        }), 200
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

# Scan endpoints
@app.route('/api/projects/<int:project_id>/scans', methods=['POST'])
def create_scan(project_id):
    """Start a new scan for a domain"""
    data = request.get_json()
    
    if not data or 'target_domain' not in data:
        return jsonify({'error': 'Target domain is required'}), 400
    
    target_domain = data['target_domain'].strip()
    
    # Basic domain validation
    if not target_domain or '.' not in target_domain:
        return jsonify({'error': 'Invalid domain format'}), 400

    # Check if at least one tool is enabled (including pipeline tools)
    enabled_tools = get_enabled_tools()
    pipeline_tools = get_pipeline_tools()
    if not enabled_tools and not pipeline_tools:
        return jsonify({'error': 'No enumeration tools are enabled. Please enable at least one tool in Settings.'}), 400
    
    db = get_db_session()
    try:
        # Verify project exists
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        # Create scan record
        scan = Scan(
            project_id=project_id,
            target_domain=target_domain,
            status='pending'
        )
        db.add(scan)
        db.commit()
        db.refresh(scan)
        
        # Start the orchestrated scan in a background thread
        start_orchestrated_scan(scan.id, target_domain)
        
        return jsonify(scan.to_dict()), 201
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/scans', methods=['GET'])
def get_all_scans():
    """Get all scans with details"""
    db = get_db_session()
    try:
        scans = db.query(Scan).join(Project).order_by(Scan.started_at.desc()).all()
        
        result = []
        for scan in scans:
            scan_dict = scan.to_dict()
            scan_dict['project_name'] = scan.project.name
            
            # Calculate unique new subdomains (subdomains that didn't exist before this scan)
            # Get all subdomains from this scan
            scan_subdomains = db.query(ScanSubdomain.subdomain_id).filter(
                ScanSubdomain.scan_id == scan.id
            ).all()
            scan_subdomain_ids = [s[0] for s in scan_subdomains]
            
            if scan_subdomain_ids:
                # Count how many of these subdomains existed before this scan started
                existing_before = db.query(func.count(ScanSubdomain.subdomain_id)).join(
                    Scan, ScanSubdomain.scan_id == Scan.id
                ).filter(
                    ScanSubdomain.subdomain_id.in_(scan_subdomain_ids),
                    Scan.started_at < scan.started_at
                ).scalar() or 0
                
                # New subdomains = total in scan - existing before
                new_subdomains = len(scan_subdomain_ids) - existing_before
            else:
                new_subdomains = 0
            
            scan_dict['new_subdomains'] = max(0, new_subdomains)
            result.append(scan_dict)
        
        return jsonify({'scans': result})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/scans/<int:scan_id>', methods=['GET'])
def get_scan(scan_id):
    """Get scan status and results"""
    db = get_db_session()
    try:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            return jsonify({'error': 'Scan not found'}), 404
        
        scan_dict = scan.to_dict()
        return jsonify(scan_dict)
    finally:
        db.close()

@app.route('/api/scans/<int:scan_id>', methods=['DELETE'])
def delete_scan(scan_id):
    """Delete a scan and its associated data"""
    db = get_db_session()
    try:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            return jsonify({'error': 'Scan not found'}), 404
        
        project_id = scan.project_id
        target_domain = scan.target_domain
        
        # Delete scan_subdomains (cascade should handle this, but be explicit)
        db.query(ScanSubdomain).filter(ScanSubdomain.scan_id == scan_id).delete()
        
        # Delete the scan
        db.delete(scan)
        db.commit()
        
        # Delete orphaned subdomains (subdomains no longer referenced by any scan)
        db.execute(text("""
            DELETE FROM subdomains
            WHERE id NOT IN (SELECT DISTINCT subdomain_id FROM scan_subdomains)
        """))
        db.commit()
        
        return jsonify({'message': 'Scan deleted successfully'}), 200
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/scans/<int:scan_id>/stop', methods=['POST'])
def stop_scan(scan_id):
    """Stop a running scan"""
    db = get_db_session()
    try:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            return jsonify({'error': 'Scan not found'}), 404
        
        if scan.status not in ['running', 'pending']:
            return jsonify({'error': f'Scan is not running (current status: {scan.status})'}), 400
        
        # Request stop
        request_stop(scan_id)
        
        # Add stop message immediately to terminal output
        from core.terminal_output import add_output
        add_output(scan_id, f"[orchestrator] Stop request received for scan {scan_id}", 'stdout')
        
        # Update scan status immediately for UI feedback
        # Orchestrator will also update it and print messages
        scan.status = 'stopped'
        scan.current_tool = None  # Clear current tool
        scan.completed_at = datetime.now(timezone.utc)
        db.commit()
        
        return jsonify({
            'message': 'Scan stop requested',
            'scan': scan.to_dict()
        }), 200
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/scans/<int:scan_id>/subdomains', methods=['GET'])
def get_scan_subdomains(scan_id):
    """Get all subdomains for a scan"""
    db = get_db_session()
    try:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            return jsonify({'error': 'Scan not found'}), 404
        
        links = db.query(ScanSubdomain).join(Subdomain).filter(
            ScanSubdomain.scan_id == scan_id
        ).order_by(ScanSubdomain.discovered_at).all()
        
        return jsonify([link.to_dict() for link in links])
    finally:
        db.close()

@app.route('/api/scans/<int:scan_id>/stream', methods=['GET'])
def stream_scan_updates(scan_id):
    """Server-Sent Events endpoint for real-time scan updates"""
    def generate():
        last_count = 0
        
        try:
            while True:
                db = get_db_session()
                try:
                    # Check scan status
                    scan = db.query(Scan).filter(Scan.id == scan_id).first()
                    
                    if not scan:
                        yield f"data: {json.dumps({'error': 'Scan not found'})}\n\n"
                        break
                    
                    # Get current subdomain count (optimized)
                    current_count = db.query(func.count(ScanSubdomain.id)).filter(
                        ScanSubdomain.scan_id == scan_id
                    ).scalar() or 0
                    
                    # Get new subdomains since last check
                    new_subdomains = []
                    if current_count > last_count:
                        links = db.query(ScanSubdomain).join(Subdomain).filter(
                            ScanSubdomain.scan_id == scan_id
                        ).order_by(ScanSubdomain.discovered_at.desc()).limit(
                            current_count - last_count
                        ).all()
                        new_subdomains = [l.to_dict() for l in reversed(links)]
                        last_count = current_count
                    
                    # Send update with progress info
                    update_data = {
                        'scan_id': scan_id,
                        'status': scan.status,
                        'subdomain_count': current_count,
                        'new_subdomains': new_subdomains,
                        'completed_at': scan.completed_at.isoformat() if scan.completed_at else None,
                        'current_tool': scan.current_tool,
                        'total_tools': scan.total_tools,
                        'completed_tools': scan.completed_tools
                    }
                    
                    yield f"data: {json.dumps(update_data)}\n\n"
                    
                    # If scan is completed, failed, or stopped, send final update and break
                    if scan.status in ['completed', 'failed', 'stopped']:
                        # Send any remaining subdomains
                        if new_subdomains:
                            yield f"data: {json.dumps(update_data)}\n\n"
                        # Send final status update to ensure UI is updated
                        yield f"data: {json.dumps(update_data)}\n\n"
                        break
                finally:
                    db.close()
                
                # Wait before next check
                time.sleep(1)
                
        except GeneratorExit:
            pass
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )

@app.route('/api/scans/<int:scan_id>/terminal', methods=['GET'])
def stream_terminal_output(scan_id):
    """Server-Sent Events endpoint for real-time terminal output"""
    def generate():
        last_timestamp = request.args.get('since')
        scan_ended = False
        end_check_count = 0
        
        try:
            while True:
                # Get terminal output since last check
                output_lines = get_output(scan_id, since_timestamp=last_timestamp)
                
                if output_lines:
                    # Update last timestamp to the most recent line
                    last_timestamp = output_lines[-1]['timestamp']
                    
                    # Send new lines
                    for line in output_lines:
                        yield f"data: {json.dumps(line)}\n\n"
                
                # Check if scan is still running
                db = get_db_session()
                try:
                    scan = db.query(Scan).filter(Scan.id == scan_id).first()
                    if scan and scan.status in ['completed', 'failed', 'stopped']:
                        if not scan_ended:
                            # First time we detect scan ended - start extended checking
                            scan_ended = True
                            end_check_count = 0
                        else:
                            end_check_count += 1
                    else:
                        scan_ended = False
                        end_check_count = 0
                finally:
                    db.close()
                
                if scan_ended:
                    # When scan is stopped/completed, continue checking for a while
                    # to ensure all final messages are captured (orchestrator may still be printing)
                    # Keep checking until we've had 10 consecutive checks with no new output
                    if end_check_count < 10:
                        # Still checking for final messages
                        time.sleep(0.3)  # Check frequently
                    else:
                        # No new output for 10 checks, safe to close
                        # One final check for any last messages
                        final_output = get_output(scan_id, since_timestamp=last_timestamp)
                        for line in final_output:
                            yield f"data: {json.dumps(line)}\n\n"
                        break
                else:
                    # Normal operation - wait before next check
                    time.sleep(0.5)
                
        except GeneratorExit:
            pass
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )

@app.route('/api/dashboard/stats', methods=['GET'])
def get_dashboard_stats():
    """Get dashboard statistics"""
    db = get_db_session()
    try:
        total_projects = db.query(Project).count()
        total_scans = db.query(Scan).count()
        completed_scans = db.query(Scan).filter(Scan.status == 'completed').count()
        active_scans = db.query(Scan).filter(Scan.status == 'running').count()
        # Count unique subdomains across all scans
        total_subdomains = db.query(func.count(func.distinct(Subdomain.subdomain))).scalar() or 0
        
        return jsonify({
            'total_projects': total_projects,
            'total_scans': total_scans,
            'completed_scans': completed_scans,
            'active_scans': active_scans,
            'total_subdomains': total_subdomains
        })
    finally:
        db.close()

@app.route('/api/subdomains/all', methods=['GET'])
def get_all_subdomains():
    """Get all subdomains across all projects with pagination"""
    db = get_db_session()
    try:
        # Pagination parameters - support both cursor and offset-based
        cursor = request.args.get('cursor', type=int)
        page = request.args.get('page', type=int)
        limit = request.args.get('limit', 100, type=int)
        search = request.args.get('search', '', type=str).strip()
        project_filter = request.args.get('project', '', type=str)
        target_filter = request.args.get('target', '', type=str)
        
        # Cap limit to prevent abuse (allow up to 5000)
        limit = min(limit, 5000)
        
        # Use cursor-based pagination if cursor is provided, otherwise use offset
        use_cursor = cursor is not None
        if not use_cursor and page:
            offset = (page - 1) * limit
        else:
            offset = None
        
        # Return unique subdomains, plus the project they were most recently seen in.
        # Use a subquery to get one specific ScanSubdomain per subdomain (latest discovered_at, max id as tie-breaker)
        # This avoids DISTINCT ON issues with ORDER BY in PostgreSQL
        latest_with_tiebreaker = db.query(
            ScanSubdomain.subdomain_id,
            func.max(ScanSubdomain.discovered_at).label('last_seen'),
            func.max(ScanSubdomain.id).label('scan_subdomain_id')
        ).group_by(ScanSubdomain.subdomain_id).subquery()

        # Base query - join to the specific ScanSubdomain to avoid duplicates
        base_query = db.query(Subdomain, Scan, Project, ScanSubdomain.tool_name, latest_with_tiebreaker.c.last_seen).join(
            latest_with_tiebreaker, latest_with_tiebreaker.c.subdomain_id == Subdomain.id
        ).join(
            ScanSubdomain, 
            (ScanSubdomain.subdomain_id == Subdomain.id) &
            (ScanSubdomain.discovered_at == latest_with_tiebreaker.c.last_seen) &
            (ScanSubdomain.id == latest_with_tiebreaker.c.scan_subdomain_id)
        ).join(
            Scan, ScanSubdomain.scan_id == Scan.id
        ).join(
            Project, Scan.project_id == Project.id
        )
        
        # Apply search filter if provided
        if search:
            # Use full-text search if available, fallback to ILIKE
            base_query = base_query.filter(
                _build_fulltext_search_filter(
                    db, search,
                    [Subdomain.subdomain]
                )
            )
        
        # Apply column filters
        if project_filter:
            try:
                project_id = int(project_filter)
                base_query = base_query.filter(Project.id == project_id)
            except ValueError:
                pass
        
        if target_filter:
            base_query = base_query.filter(Scan.target_domain == target_filter)
        
        # Get total count (only if using offset pagination)
        total = None
        if not use_cursor:
            total = base_query.count()
        
        # Get paginated results
        if use_cursor:
            # Cursor-based pagination - much faster for large datasets
            if cursor:
                base_query = base_query.filter(Subdomain.id < cursor)
            
            base_query = base_query.order_by(Subdomain.id.desc())
            subdomains = base_query.limit(limit + 1).all()
            
            has_more = len(subdomains) > limit
            if has_more:
                subdomains = subdomains[:-1]
            
            next_cursor = subdomains[-1][0].id if subdomains and has_more else None
            
            result = []
            for subdomain, scan, project, tool_name, _last_seen in subdomains:
                subdomain_dict = subdomain.to_dict()
                subdomain_dict['project_name'] = project.name
                subdomain_dict['project_id'] = project.id
                subdomain_dict['tool_name'] = tool_name
                result.append(subdomain_dict)
            
            pagination = {
                'limit': limit,
                'cursor': next_cursor,
                'has_more': has_more
            }
        else:
            # Offset-based pagination (for backward compatibility)
            subdomains = base_query.order_by(latest_with_tiebreaker.c.last_seen.desc()).offset(offset).limit(limit).all()
            
            result = []
            for subdomain, scan, project, tool_name, _last_seen in subdomains:
                subdomain_dict = subdomain.to_dict()
                subdomain_dict['project_name'] = project.name
                subdomain_dict['project_id'] = project.id
                subdomain_dict['tool_name'] = tool_name
                result.append(subdomain_dict)
            
            pagination = {
                'page': page or 1,
                'limit': limit,
                'total': total,
                'pages': (total + limit - 1) // limit if total else 0
            }
        
        return jsonify({
            'subdomains': result,
            'pagination': pagination
        })
    finally:
        db.close()

@app.route('/api/subdomains/<int:subdomain_id>', methods=['DELETE'])
def delete_subdomain(subdomain_id):
    """Delete a specific subdomain"""
    db = get_db_session()
    try:
        subdomain = db.query(Subdomain).filter(Subdomain.id == subdomain_id).first()
        
        if not subdomain:
            return jsonify({'error': 'Subdomain not found'}), 404

        affected_scan_ids = [row[0] for row in db.query(ScanSubdomain.scan_id).filter(
            ScanSubdomain.subdomain_id == subdomain_id
        ).distinct().all()]
        
        # Delete the subdomain
        db.delete(subdomain)
        db.commit()
        
        # Update scan subdomain counts for affected scans
        for scan_id in affected_scan_ids:
            scan = db.query(Scan).filter(Scan.id == scan_id).first()
            if scan:
                scan.subdomain_count = db.query(ScanSubdomain).filter(
                    ScanSubdomain.scan_id == scan_id
                ).count()
        db.commit()
        
        return jsonify({'message': 'Subdomain deleted successfully', 'affected_scans': affected_scan_ids}), 200
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/subdomains/bulk-delete', methods=['POST'])
def bulk_delete_subdomains():
    """Delete multiple subdomains at once"""
    data = request.get_json()
    
    if not data or 'subdomain_ids' not in data:
        return jsonify({'error': 'subdomain_ids array is required'}), 400
    
    subdomain_ids = data['subdomain_ids']
    
    if not isinstance(subdomain_ids, list) or len(subdomain_ids) == 0:
        return jsonify({'error': 'subdomain_ids must be a non-empty array'}), 400
    
    db = get_db_session()
    try:
        # Get all subdomains to be deleted and collect affected scan_ids
        subdomains = db.query(Subdomain).filter(Subdomain.id.in_(subdomain_ids)).all()
        
        if not subdomains:
            return jsonify({'error': 'No subdomains found with provided IDs'}), 404
        
        affected_scan_ids = set(
            row[0]
            for row in db.query(ScanSubdomain.scan_id).filter(
                ScanSubdomain.subdomain_id.in_(subdomain_ids)
            ).distinct().all()
        )
        deleted_count = len(subdomains)
        
        # Delete all subdomains
        for subdomain in subdomains:
            db.delete(subdomain)
        
        db.commit()
        
        # Update subdomain counts for all affected scans
        for scan_id in affected_scan_ids:
            scan = db.query(Scan).filter(Scan.id == scan_id).first()
            if scan:
                scan.subdomain_count = db.query(ScanSubdomain).filter(
                    ScanSubdomain.scan_id == scan_id
                ).count()
        
        db.commit()
        
        return jsonify({
            'message': f'{deleted_count} subdomain(s) deleted successfully',
            'deleted_count': deleted_count,
            'affected_scans': list(affected_scan_ids)
        }), 200
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/subdomains/export', methods=['POST'])
def export_subdomains():
    """Export selected subdomains as text file (one subdomain per line)"""
    from flask import make_response
    
    data = request.get_json()
    if not data or 'subdomain_ids' not in data:
        return jsonify({'error': 'subdomain_ids array is required'}), 400
    
    subdomain_ids = data['subdomain_ids']
    
    if not isinstance(subdomain_ids, list) or len(subdomain_ids) == 0:
        return jsonify({'error': 'subdomain_ids must be a non-empty array'}), 400
    
    db = get_db_session()
    try:
        subdomains = db.query(Subdomain).filter(Subdomain.id.in_(subdomain_ids)).order_by(Subdomain.subdomain).all()
        
        if not subdomains:
            return jsonify({'error': 'No subdomains found'}), 404
        
        # Create text file with one subdomain per line
        output = '\n'.join([s.subdomain for s in subdomains if s.subdomain])
        
        response = make_response(output)
        response.headers['Content-Type'] = 'text/plain'
        response.headers['Content-Disposition'] = 'attachment; filename=subdomains.txt'
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/settings/export', methods=['GET'])
def export_settings():
    """Export settings (tools.yaml and API keys) as YAML"""
    from flask import make_response
    from tool_executor.common import load_tools_config
    
    try:
        # Get tools config
        tools_config = load_tools_config()
        
        # Get API keys
        db = get_db_session()
        try:
            settings = db.query(Setting).filter(Setting.key.like('%api_key%')).all()
            api_keys = {s.key: s.value for s in settings}
            
            # Get wordlists
            wordlist_settings = db.query(Setting).filter(Setting.key.like('wordlist_%')).all()
            wordlists = {}
            for setting in wordlist_settings:
                wordlist_name = setting.key.replace('wordlist_', '', 1)
                wordlists[wordlist_name] = setting.value
            
            # Get input files
            input_file_settings = db.query(Setting).filter(Setting.key.like('input_file_%')).all()
            input_files = {}
            for setting in input_file_settings:
                input_file_name = setting.key.replace('input_file_', '', 1)
                input_files[input_file_name] = setting.value
        finally:
            db.close()
        
        # Create export data
        export_data = {
            'tools': tools_config,
            'api_keys': api_keys,
            'wordlists': wordlists,
            'input_files': input_files,
            'exported_at': datetime.now().isoformat()
        }
        
        # Convert to YAML
        yaml_content = yaml.dump(export_data, default_flow_style=False, sort_keys=False, allow_unicode=True)
        
        response = make_response(yaml_content)
        response.headers['Content-Type'] = 'application/x-yaml'
        response.headers['Content-Disposition'] = 'attachment; filename=settings_export.yaml'
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/import', methods=['POST'])
def import_settings():
    """Import settings from YAML file"""
    from tool_executor.common import save_tools_config
    
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Read and parse YAML
        yaml_content = file.read().decode('utf-8')
        import_data = yaml.safe_load(yaml_content)
        
        if not import_data:
            return jsonify({'error': 'Invalid YAML file'}), 400
        
        db = get_db_session()
        try:
            # Import tools configuration
            if 'tools' in import_data:
                tools_config = import_data['tools']
                # Ensure the structure is correct (should have 'tools' key at top level)
                if not isinstance(tools_config, dict):
                    return jsonify({'error': 'Invalid tools configuration structure'}), 400
                
                # If tools_config doesn't have 'tools' key, it might be the tools dict itself
                if 'tools' not in tools_config:
                    # Check if it looks like a tools dict (has tool names as keys with 'enabled' or 'type')
                    if any(isinstance(v, dict) and ('enabled' in v or 'type' in v) for v in tools_config.values()):
                        tools_config = {'tools': tools_config}
                    else:
                        return jsonify({'error': 'Invalid tools configuration structure'}), 400
                
                if save_tools_config(tools_config):
                    pass  # Success
                else:
                    return jsonify({'error': 'Failed to save tools configuration'}), 500
            
            # Import API keys
            if 'api_keys' in import_data:
                api_keys = import_data['api_keys']
                for key, value in api_keys.items():
                    if value:  # Only import non-empty values
                        setting = db.query(Setting).filter(Setting.key == key).first()
                        if setting:
                            setting.value = value
                        else:
                            setting = Setting(key=key, value=value)
                            db.add(setting)
                
                db.commit()
            
            # Import wordlists
            if 'wordlists' in import_data:
                wordlists = import_data['wordlists']
                for name, path in wordlists.items():
                    if path:  # Only import non-empty paths
                        setting_key = f'wordlist_{name}'
                        setting = db.query(Setting).filter(Setting.key == setting_key).first()
                        if setting:
                            setting.value = path
                        else:
                            setting = Setting(key=setting_key, value=path)
                            db.add(setting)
                
                db.commit()
            
            # Import input files
            if 'input_files' in import_data:
                input_files = import_data['input_files']
                for name, path in input_files.items():
                    if path:  # Only import non-empty paths
                        setting_key = f'input_file_{name}'
                        setting = db.query(Setting).filter(Setting.key == setting_key).first()
                        if setting:
                            setting.value = path
                        else:
                            setting = Setting(key=setting_key, value=path)
                            db.add(setting)
                
                db.commit()
            
            return jsonify({'message': 'Settings imported successfully'})
        finally:
            db.close()
    except yaml.YAMLError as e:
        return jsonify({'error': f'Invalid YAML format: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get all settings"""
    db = get_db_session()
    try:
        settings = db.query(Setting).all()
        settings_dict = {s.key: s.value for s in settings}
        
        # Return default values if not set
        defaults = {
            'tool_subfinder_enabled': 'true',
            'tool_crtsh_enabled': 'true',
            'tool_sublist3r_enabled': 'true',
            'tool_sublist3r_path': 'sublist3r',
            'tool_oneforall_enabled': 'true',
            'tool_oneforall_path': 'python3 /opt/OneForAll/oneforall.py',
            'tool_assetfinder_enabled': 'true',
            'tool_assetfinder_path': 'assetfinder',
            'tool_censys_enabled': 'false',
            'tool_censys_api_key': '',
            'tool_securitytrails_enabled': 'false',
            'tool_securitytrails_api_key': '',
            'tool_wayback_enabled': 'true',
            'tool_commoncrawl_enabled': 'true',
            'tool_virustotal_enabled': 'false',
            'tool_virustotal_api_key': '',
            'tool_active_enum_enabled': 'false',
            'tool_alterx_path': 'alterx',
            'tool_dnsx_path': 'dnsx'
        }
        
        for key, default_value in defaults.items():
            if key not in settings_dict:
                settings_dict[key] = default_value
        
        return jsonify(settings_dict)
    finally:
        db.close()

@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Update settings"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    db = get_db_session()
    try:
        for key, value in data.items():
            # Update or create setting
            setting = db.query(Setting).filter(Setting.key == key).first()
            if setting:
                setting.value = str(value)
                setting.updated_at = datetime.now()
            else:
                setting = Setting(key=key, value=str(value))
                db.add(setting)
        
        db.commit()
        return jsonify({'message': 'Settings updated successfully'}), 200
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

# ============================================
# Tool Configuration Endpoints
# ============================================

@app.route('/api/tools', methods=['GET'])
def get_tools_list():
    """Get list of all tools with their status"""
    try:
        config = load_tools_config()
        tools = config.get('tools', {})
        
        result = []
        for name, tool in tools.items():
            result.append({
                'name': name,
                'type': tool.get('type', 'cli'),
                'enabled': tool.get('enabled', False),
                'description': tool.get('description', ''),
                'requires_api_key': bool(tool.get('api_key_setting'))
            })
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tools/config', methods=['GET'])
def get_tools_config():
    """Get full tools configuration as YAML"""
    try:
        import copy
        config = load_tools_config()
        
        # Create a formatted copy for display (don't modify original)
        formatted_config = copy.deepcopy(config)
        
        # Format args for all tools
        if 'tools' in formatted_config:
            for tool_name, tool_config in formatted_config['tools'].items():
                if 'args' in tool_config:
                    tool_config['args'] = format_args_for_display(tool_config['args'])
                # Format pipeline steps args
                if 'steps' in tool_config:
                    for step in tool_config['steps']:
                        if 'args' in step:
                            step['args'] = format_args_for_display(step['args'])
        
        yaml_content = yaml.dump(formatted_config, default_flow_style=False, sort_keys=False)
        return jsonify({
            'config': config,
            'yaml': yaml_content
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tools/config', methods=['PUT'])
def update_tools_config():
    """Update full tools configuration from YAML"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    try:
        # Accept either YAML string or config object
        if 'yaml' in data:
            config = yaml.safe_load(data['yaml'])
        elif 'config' in data:
            config = data['config']
        else:
            return jsonify({'error': 'Either yaml or config field required'}), 400
        
        # Validate structure
        if 'tools' not in config:
            return jsonify({'error': 'Invalid config: missing tools section'}), 400
        
        if save_tools_config(config):
            return jsonify({'message': 'Configuration saved successfully'})
        else:
            return jsonify({'error': 'Failed to save configuration'}), 500
    except yaml.YAMLError as e:
        return jsonify({'error': f'Invalid YAML: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tools/<tool_name>', methods=['GET'])
def get_tool(tool_name):
    """Get configuration for a specific tool"""
    try:
        import copy
        tool_config = get_tool_config(tool_name)
        if not tool_config:
            return jsonify({'error': f'Tool {tool_name} not found'}), 404
        
        # Create a copy for formatting (don't modify original)
        formatted_config = copy.deepcopy(tool_config)
        
        # Format args for display (combine option-value pairs)
        if 'args' in formatted_config:
            formatted_config['args'] = format_args_for_display(formatted_config['args'])
        
        # Format pipeline steps args
        if 'steps' in formatted_config:
            for step in formatted_config['steps']:
                if 'args' in step:
                    step['args'] = format_args_for_display(step['args'])
        
        yaml_content = yaml.dump({tool_name: formatted_config}, default_flow_style=False, sort_keys=False)
        return jsonify({
            'name': tool_name,
            'config': tool_config,
            'yaml': yaml_content
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tools/<tool_name>', methods=['PUT'])
def update_tool(tool_name):
    """Update configuration for a specific tool"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    try:
        config = load_tools_config()
        
        # Ensure config is a dict
        if config is None:
            config = {}
        
        # Accept either YAML string or config object
        if 'yaml' in data:
            tool_config = yaml.safe_load(data['yaml'])
            # If YAML contains the tool name as key, extract it
            if tool_config and isinstance(tool_config, dict) and tool_name in tool_config:
                tool_config = tool_config[tool_name]
        elif 'config' in data:
            tool_config = data['config']
        else:
            return jsonify({'error': 'Either yaml or config field required'}), 400
        
        # Update tool in config
        if not isinstance(config, dict):
            config = {}
        if 'tools' not in config:
            config['tools'] = {}
        
        config['tools'][tool_name] = tool_config
        
        if save_tools_config(config):
            return jsonify({'message': f'Tool {tool_name} updated successfully'})
        else:
            return jsonify({'error': 'Failed to save configuration'}), 500
    except yaml.YAMLError as e:
        return jsonify({'error': f'Invalid YAML: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tools/<tool_name>', methods=['DELETE'])
def delete_tool(tool_name):
    """Delete a tool from configuration"""
    try:
        config = load_tools_config()
        
        # Ensure config is a dict
        if config is None:
            config = {}
        if 'tools' not in config:
            config['tools'] = {}
        
        if tool_name not in config.get('tools', {}):
            return jsonify({'error': f'Tool {tool_name} not found'}), 404
        
        del config['tools'][tool_name]
        
        if save_tools_config(config):
            return jsonify({'message': f'Tool {tool_name} deleted successfully'})
        else:
            return jsonify({'error': 'Failed to save configuration'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tools/<tool_name>/toggle', methods=['POST'])
def toggle_tool(tool_name):
    """Toggle tool enabled/disabled state"""
    try:
        config = load_tools_config()
        
        if tool_name not in config.get('tools', {}):
            return jsonify({'error': f'Tool {tool_name} not found'}), 404
        
        current_state = config['tools'][tool_name].get('enabled', False)
        config['tools'][tool_name]['enabled'] = not current_state
        
        if save_tools_config(config):
            return jsonify({
                'message': f'Tool {tool_name} {"enabled" if not current_state else "disabled"}',
                'enabled': not current_state
            })
        else:
            return jsonify({'error': 'Failed to save configuration'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tools/templates', methods=['GET'])
def get_tool_templates():
    """Get templates for creating new tools"""
    templates = {
        'cli': {
            'enabled': False,
            'type': 'cli',
            'description': 'New CLI tool',
            'command': 'tool_name',
            'args': ['-d', '{domain}'],
            'output': 'lines',
            'path_setting': 'tool_newtool_path'
        },
        'api': {
            'enabled': False,
            'type': 'api',
            'description': 'New API tool',
            'method': 'GET',
            'url': 'https://api.example.com/subdomains/{domain}',
            'headers': {
                'Authorization': 'Bearer {api_key}'
            },
            'api_key_setting': 'tool_newtool_api_key',
            'timeout': 30,
            'response_type': 'json',
            'extract': {
                'type': 'json_path',
                'path': 'data.subdomains'
            }
        },
        'pipeline': {
            'enabled': False,
            'type': 'pipeline',
            'description': 'New pipeline tool',
            'run_after': 'passive',
            'input': 'scan_subdomains',
            'steps': [
                {
                    'name': 'step1',
                    'command': 'tool1',
                    'args': ['-l', '{input_file}']
                },
                {
                    'name': 'step2',
                    'command': 'tool2',
                    'args': [],
                    'pipe_from': 'step1'
                }
            ]
        }
    }
    
    return jsonify(templates)


@app.route('/api/tools/api-keys', methods=['GET'])
def get_api_keys():
    """Get list of API keys with masked values"""
    db = get_db_session()
    try:
        config = load_tools_config()
        api_keys = []
        
        for name, tool in config.get('tools', {}).items():
            api_key_setting = tool.get('api_key_setting')
            auth_setting = tool.get('auth', {}).get('setting')
            
            setting_key = api_key_setting or auth_setting
            if setting_key:
                setting = db.query(Setting).filter(Setting.key == setting_key).first()
                has_key = bool(setting and setting.value and setting.value.strip())
                
                api_keys.append({
                    'tool': name,
                    'setting_key': setting_key,
                    'has_key': has_key,
                    'masked_value': (setting.value[:4] + '***' + setting.value[-4:]) if has_key and len(setting.value) > 8 else ('***' if has_key else '')
                })
        
        return jsonify(api_keys)
    finally:
        db.close()


@app.route('/api/tools/api-keys/<setting_key>', methods=['PUT'])
def update_api_key(setting_key):
    """Update an API key"""
    data = request.get_json()
    
    if not data or 'value' not in data:
        return jsonify({'error': 'value field required'}), 400
    
    db = get_db_session()
    try:
        setting = db.query(Setting).filter(Setting.key == setting_key).first()
        
        if setting:
            setting.value = data['value']
            setting.updated_at = datetime.now()
        else:
            setting = Setting(key=setting_key, value=data['value'])
            db.add(setting)
        
        db.commit()
        return jsonify({'message': 'API key updated successfully'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

# ============================================
# Wordlist Management Endpoints
# ============================================

@app.route('/api/wordlists', methods=['GET'])
def get_wordlists():
    """Get all wordlist files"""
    db = get_db_session()
    try:
        settings = db.query(Setting).filter(Setting.key.like('wordlist_%')).all()
        wordlists = []
        
        for setting in settings:
            # Extract wordlist name from key (wordlist_<name>)
            wordlist_name = setting.key.replace('wordlist_', '', 1)
            wordlists.append({
                'name': wordlist_name,
                'path': setting.value,
                'placeholder': f'{{wordlist_{wordlist_name}}}',
                'updated_at': setting.updated_at.isoformat() if setting.updated_at else None
            })
        
        # Sort by name
        wordlists.sort(key=lambda x: x['name'])
        
        return jsonify(wordlists)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/wordlists', methods=['POST'])
def create_wordlist():
    """Create a new wordlist entry"""
    data = request.get_json()
    
    if not data or 'name' not in data or 'path' not in data:
        return jsonify({'error': 'name and path fields are required'}), 400
    
    name = data['name'].strip().lower()
    path = data['path'].strip()
    
    if not name:
        return jsonify({'error': 'Wordlist name cannot be empty'}), 400
    
    if not path:
        return jsonify({'error': 'Wordlist path cannot be empty'}), 400
    
    # Validate name (alphanumeric and underscores only)
    if not name.replace('_', '').isalnum():
        return jsonify({'error': 'Wordlist name can only contain letters, numbers, and underscores'}), 400
    
    db = get_db_session()
    try:
        setting_key = f'wordlist_{name}'
        
        # Check if wordlist already exists
        existing = db.query(Setting).filter(Setting.key == setting_key).first()
        if existing:
            return jsonify({'error': f'Wordlist "{name}" already exists'}), 400
        
        # Create new wordlist
        setting = Setting(key=setting_key, value=path)
        db.add(setting)
        db.commit()
        
        return jsonify({
            'message': f'Wordlist "{name}" created successfully',
            'wordlist': {
                'name': name,
                'path': path,
                'placeholder': f'{{wordlist_{name}}}'
            }
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/wordlists/<wordlist_name>', methods=['PUT'])
def update_wordlist(wordlist_name):
    """Update a wordlist entry"""
    data = request.get_json()
    
    if not data or 'path' not in data:
        return jsonify({'error': 'path field is required'}), 400
    
    path = data['path'].strip()
    if not path:
        return jsonify({'error': 'Wordlist path cannot be empty'}), 400
    
    db = get_db_session()
    try:
        setting_key = f'wordlist_{wordlist_name}'
        setting = db.query(Setting).filter(Setting.key == setting_key).first()
        
        if not setting:
            return jsonify({'error': f'Wordlist "{wordlist_name}" not found'}), 404
        
        setting.value = path
        setting.updated_at = datetime.now()
        db.commit()
        
        return jsonify({
            'message': f'Wordlist "{wordlist_name}" updated successfully',
            'wordlist': {
                'name': wordlist_name,
                'path': path,
                'placeholder': f'{{wordlist_{wordlist_name}}}'
            }
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/wordlists/<wordlist_name>', methods=['DELETE'])
def delete_wordlist(wordlist_name):
    """Delete a wordlist entry"""
    db = get_db_session()
    try:
        setting_key = f'wordlist_{wordlist_name}'
        setting = db.query(Setting).filter(Setting.key == setting_key).first()
        
        if not setting:
            return jsonify({'error': f'Wordlist "{wordlist_name}" not found'}), 404
        
        db.delete(setting)
        db.commit()
        
        return jsonify({'message': f'Wordlist "{wordlist_name}" deleted successfully'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

# ============================================
# Input File Management Endpoints
# ============================================

@app.route('/api/input-files', methods=['GET'])
def get_input_files():
    """Get all input file entries"""
    db = get_db_session()
    try:
        settings = db.query(Setting).filter(Setting.key.like('input_file_%')).all()
        input_files = []
        
        for setting in settings:
            # Extract input file name from key (input_file_<name>)
            input_file_name = setting.key.replace('input_file_', '', 1)
            input_files.append({
                'name': input_file_name,
                'path': setting.value,
                'placeholder': f'{{input_file_{input_file_name}}}',
                'updated_at': setting.updated_at.isoformat() if setting.updated_at else None
            })
        
        # Sort by name
        input_files.sort(key=lambda x: x['name'])
        
        return jsonify(input_files)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/input-files', methods=['POST'])
def create_input_file():
    """Create a new input file entry"""
    data = request.get_json()
    
    if not data or 'name' not in data or 'path' not in data:
        return jsonify({'error': 'name and path fields are required'}), 400
    
    name = data['name'].strip().lower()
    path = data['path'].strip()
    
    if not name:
        return jsonify({'error': 'Input file name cannot be empty'}), 400
    
    if not path:
        return jsonify({'error': 'Input file path cannot be empty'}), 400
    
    # Validate name (alphanumeric and underscores only)
    if not name.replace('_', '').isalnum():
        return jsonify({'error': 'Input file name can only contain letters, numbers, and underscores'}), 400
    
    db = get_db_session()
    try:
        setting_key = f'input_file_{name}'
        
        # Check if input file already exists
        existing = db.query(Setting).filter(Setting.key == setting_key).first()
        if existing:
            return jsonify({'error': f'Input file "{name}" already exists'}), 400
        
        # Create new input file
        setting = Setting(key=setting_key, value=path)
        db.add(setting)
        db.commit()
        
        return jsonify({
            'message': f'Input file "{name}" created successfully',
            'input_file': {
                'name': name,
                'path': path,
                'placeholder': f'{{input_file_{name}}}'
            }
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/input-files/<input_file_name>', methods=['PUT'])
def update_input_file(input_file_name):
    """Update an input file entry"""
    data = request.get_json()
    
    if not data or 'path' not in data:
        return jsonify({'error': 'path field is required'}), 400
    
    path = data['path'].strip()
    if not path:
        return jsonify({'error': 'Input file path cannot be empty'}), 400
    
    db = get_db_session()
    try:
        setting_key = f'input_file_{input_file_name}'
        setting = db.query(Setting).filter(Setting.key == setting_key).first()
        
        if not setting:
            return jsonify({'error': f'Input file "{input_file_name}" not found'}), 404
        
        setting.value = path
        setting.updated_at = datetime.now()
        db.commit()
        
        return jsonify({
            'message': f'Input file "{input_file_name}" updated successfully',
            'input_file': {
                'name': input_file_name,
                'path': path,
                'placeholder': f'{{input_file_{input_file_name}}}'
            }
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/input-files/<input_file_name>', methods=['DELETE'])
def delete_input_file(input_file_name):
    """Delete an input file entry"""
    db = get_db_session()
    try:
        setting_key = f'input_file_{input_file_name}'
        setting = db.query(Setting).filter(Setting.key == setting_key).first()
        
        if not setting:
            return jsonify({'error': f'Input file "{input_file_name}" not found'}), 404
        
        db.delete(setting)
        db.commit()
        
        return jsonify({'message': f'Input file "{input_file_name}" deleted successfully'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@app.route('/api/database/stats', methods=['GET'])
def get_db_stats():
    """Get database statistics including table sizes, index usage, and connection pool info"""
    try:
        stats = get_database_stats()
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/database/maintenance', methods=['POST'])
def run_db_maintenance():
    """Run database maintenance (VACUUM ANALYZE)"""
    try:
        success = run_maintenance()
        if success:
            return jsonify({'message': 'Database maintenance completed successfully'}), 200
        else:
            return jsonify({'error': 'Database maintenance failed'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/database/clear', methods=['POST'])
def clear_database():
    """Clear all data from the database (keep settings)"""
    db = get_db_session()
    try:
        # Delete in order to respect foreign key constraints
        # 0. Delete legacy scan_subdomains backup rows if present
        legacy_exists = db.execute(
            text("SELECT to_regclass('public.scan_subdomains_legacy') IS NOT NULL")
        ).scalar()
        if legacy_exists:
            db.execute(text("DELETE FROM scan_subdomains_legacy"))
            db.commit()

        # 1. Delete scan_subdomains (junction table)
        scan_subdomain_count = db.query(ScanSubdomain).delete()
        db.commit()
        
        # 2. Delete scans
        scan_count = db.query(Scan).delete()
        db.commit()
        
        # 3. Delete subdomains
        subdomain_count = db.query(Subdomain).delete()
        db.commit()
        
        # 4. Delete projects
        project_count = db.query(Project).delete()
        db.commit()
        
        return jsonify({
            'message': 'Database cleared successfully',
            'deleted': {
                'projects': project_count,
                'scans': scan_count,
                'subdomains': subdomain_count,
                'scan_subdomains': scan_subdomain_count
            }
        }), 200
    except Exception as e:
        db.rollback()
        print(f"Error clearing database: {str(e)}")
        return jsonify({'error': 'Failed to clear database', 'details': str(e)}), 500
    finally:
        db.close()

if __name__ == '__main__':
    app.run(debug=app.config['DEBUG'], host='0.0.0.0', port=5000)

