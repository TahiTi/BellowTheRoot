"""
Common utilities for tool executors
Shared functions for config, validation, and database operations
"""
import os
import re
import yaml
import threading
from datetime import datetime, timezone
from core.database import SessionLocal
from core.database import Subdomain, ScanSubdomain, Setting
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func


# Path to tools configuration
TOOLS_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'tools.yaml')


# ============================================
# Configuration Functions
# ============================================

def load_tools_config():
    """Load tools configuration from YAML file"""
    try:
        with open(TOOLS_CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[executor] Error loading tools.yaml: {e}")
        return {'tools': {}}


def save_tools_config(config):
    """Save tools configuration to YAML file"""
    try:
        with open(TOOLS_CONFIG_PATH, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        return True
    except Exception as e:
        print(f"[executor] Error saving tools.yaml: {e}")
        return False


def get_tool_config(tool_name):
    """Get configuration for a specific tool"""
    config = load_tools_config()
    return config.get('tools', {}).get(tool_name)


def is_tool_enabled(tool_name):
    """Check if a tool is enabled"""
    tool_config = get_tool_config(tool_name)
    if tool_config:
        return tool_config.get('enabled', False)
    return False


def get_enabled_tools():
    """Get list of enabled individual tools (excludes pipeline tools that run after individual tools)"""
    config = load_tools_config()
    enabled = []
    for name, tool in config.get('tools', {}).items():
        if tool.get('enabled', False) and tool.get('run_after') != 'passive':
            enabled.append(name)
    return enabled


def get_pipeline_tools():
    """Get pipeline tools that should run after individual tools complete"""
    config = load_tools_config()
    pipeline = []
    for name, tool in config.get('tools', {}).items():
        if tool.get('enabled', False) and tool.get('run_after') == 'passive':
            pipeline.append(name)
    return pipeline


# ============================================
# Database Functions
# ============================================

def get_setting(key):
    """Get a setting value from database"""
    db = SessionLocal()
    try:
        setting = db.query(Setting).filter(Setting.key == key).first()
        if setting and setting.value:
            return setting.value
        return None
    finally:
        db.close()


def get_scan_subdomains(scan_id):
    """Get all subdomains discovered in a scan"""
    db = SessionLocal()
    try:
        results = db.query(Subdomain.subdomain).join(
            ScanSubdomain, ScanSubdomain.subdomain_id == Subdomain.id
        ).filter(
            ScanSubdomain.scan_id == scan_id
        ).all()
        return [r[0] for r in results]
    finally:
        db.close()


def save_subdomain(db, subdomain, target_domain, scan_id, tool_name=None):
    """Save a subdomain to database"""
    now = datetime.now(timezone.utc)
    
    # Upsert subdomain
    sd_insert = insert(Subdomain).values(
        subdomain=subdomain,
        target_domain=target_domain,
        first_seen_at=now,
        last_seen_at=now,
        uri=f"https://{subdomain}"
    )
    sd_excluded = sd_insert.excluded
    upsert_sd = sd_insert.on_conflict_do_update(
        index_elements=[Subdomain.subdomain],
        set_={
            'last_seen_at': func.greatest(Subdomain.last_seen_at, sd_excluded.last_seen_at),
            'target_domain': func.coalesce(Subdomain.target_domain, sd_excluded.target_domain),
        }
    ).returning(Subdomain.id)
    
    subdomain_id = db.execute(upsert_sd).scalar()
    
    # Link scan -> subdomain with tool name
    link_stmt = insert(ScanSubdomain).values(
        scan_id=scan_id,
        subdomain_id=subdomain_id,
        discovered_at=now,
        tool_name=tool_name
    ).on_conflict_do_nothing(
        index_elements=[ScanSubdomain.scan_id, ScanSubdomain.subdomain_id]
    )
    res = db.execute(link_stmt)
    
    # Trigger automatic probing in background thread
    is_new_subdomain = res.rowcount and res.rowcount > 0
    if is_new_subdomain:
        _trigger_auto_probe(subdomain, subdomain_id)
    
    return is_new_subdomain


def _trigger_auto_probe(subdomain_name: str, subdomain_id: int):
    """Trigger automatic probing for a newly discovered subdomain"""
    def probe_in_background():
        try:
            from core.probe_service import get_probe_service
            from core.database import SessionLocal
            from core.database import Subdomain
            
            probe_service = get_probe_service()
            result = probe_service.probe_subdomain(subdomain_name)
            
            # Update database with probe result
            db = SessionLocal()
            try:
                subdomain = db.query(Subdomain).filter(Subdomain.id == subdomain_id).first()
                if subdomain:
                    subdomain.is_online = result['status']
                    subdomain.probe_http_status = result.get('http_status_code')
                    subdomain.probe_https_status = result.get('https_status_code')
                    db.commit()
            except Exception as e:
                db.rollback()
                print(f"[probe] Error updating probe result for {subdomain_name}: {str(e)}")
            finally:
                db.close()
        except Exception as e:
            print(f"[probe] Error probing {subdomain_name}: {str(e)}")
    
    # Start probing in background thread
    thread = threading.Thread(target=probe_in_background, daemon=True)
    thread.start()


# ============================================
# Utility Functions
# ============================================

def get_tool_command(tool_config):
    """Get tool command from config"""
    return tool_config.get('command', '')


def substitute_vars(value, variables):
    """Substitute {var} placeholders in a string"""
    if isinstance(value, str):
        for var_name, var_value in variables.items():
            value = value.replace(f'{{{var_name}}}', str(var_value))
        return value
    elif isinstance(value, list):
        return [substitute_vars(v, variables) for v in value]
    elif isinstance(value, dict):
        return {k: substitute_vars(v, variables) for k, v in value.items()}
    return value


def get_wordlists():
    """Get all wordlist settings from database"""
    db = SessionLocal()
    try:
        settings = db.query(Setting).filter(Setting.key.like('wordlist_%')).all()
        wordlists = {}
        for setting in settings:
            # Extract wordlist name from key (wordlist_<name>)
            wordlist_name = setting.key.replace('wordlist_', '', 1)
            wordlists[f'wordlist_{wordlist_name}'] = setting.value
        return wordlists
    finally:
        db.close()


def get_input_files():
    """Get all input file settings from database"""
    db = SessionLocal()
    try:
        settings = db.query(Setting).filter(Setting.key.like('input_file_%')).all()
        input_files = {}
        for setting in settings:
            # Extract input file name from key (input_file_<name>)
            input_file_name = setting.key.replace('input_file_', '', 1)
            input_files[f'input_file_{input_file_name}'] = setting.value
        return input_files
    finally:
        db.close()


def is_valid_subdomain(subdomain, target_domain):
    """Validate that subdomain belongs to target domain"""
    subdomain = subdomain.strip().lower()
    target_domain = target_domain.strip().lower()
    
    if not subdomain or not target_domain:
        return False
    
    # Remove wildcard prefix
    if subdomain.startswith('*.'):
        subdomain = subdomain[2:]
    
    if subdomain.endswith('.' + target_domain) or subdomain == target_domain:
        return True
    
    return False


def strip_ansi(text):
    """Remove ANSI escape sequences from text"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def format_args_for_display(args):
    """
    Format args list for display by combining option-value pairs on one line.
    For example: ['-d', '{domain}', '-silent'] -> ['-d {domain}', '-silent']
    This function is idempotent - it won't re-combine already combined args.
    """
    if not isinstance(args, list):
        return args
    
    formatted = []
    i = 0
    while i < len(args):
        arg = args[i]
        # Check if this is already a combined option-value pair
        if isinstance(arg, str) and ' ' in arg:
            parts = arg.split(' ', 1)
            # If it looks like a combined option-value (option starts with -), keep it as-is
            if len(parts) == 2 and parts[0].startswith('-'):
                formatted.append(arg)
                i += 1
                continue
        
        # Check if this looks like an option (starts with -)
        if isinstance(arg, str) and arg.startswith('-') and i + 1 < len(args):
            next_arg = args[i + 1]
            # Check if next arg is a value (not an option, not empty)
            if isinstance(next_arg, str) and not next_arg.startswith('-') and next_arg.strip():
                # Combine option and value
                formatted.append(f"{arg} {next_arg}")
                i += 2
                continue
        formatted.append(arg)
        i += 1
    
    return formatted


def expand_args_for_execution(args):
    """
    Expand args list for execution by splitting combined option-value pairs.
    For example: ['-d {domain}', '-silent'] -> ['-d', '{domain}', '-silent']
    Handles both combined strings and already-separated args.
    """
    if not isinstance(args, list):
        return args
    
    expanded = []
    for arg in args:
        if isinstance(arg, str) and ' ' in arg:
            # Check if it looks like a combined option-value pair (option starts with -)
            parts = arg.split(' ', 1)
            if len(parts) == 2 and parts[0].startswith('-'):
                expanded.extend(parts)
            else:
                expanded.append(arg)
        else:
            expanded.append(arg)
    
    return expanded

