"""
API Tool Executor
Executes HTTP API requests and parses responses
"""
import re
import json
import requests
from core.database import SessionLocal
from core.terminal_output import TerminalOutputCapture
from .common import (
    get_setting,
    substitute_vars,
    is_valid_subdomain,
    save_subdomain
)


def run_api_tool(tool_name, tool_config, scan_id, target_domain):
    """Execute an API tool and process its response"""
    db = SessionLocal()
    
    # Capture terminal output
    with TerminalOutputCapture(scan_id, tool_name):
        try:
            print(f"[{tool_name}] Starting scan for {target_domain} (scan {scan_id})")
            
            # Get API key if needed
            api_key = ''
            api_key_setting = tool_config.get('api_key_setting')
            if api_key_setting:
                api_key = get_setting(api_key_setting) or ''
                if not api_key:
                    print(f"[{tool_name}] No API key configured, skipping")
                    return
            
            variables = {
                'domain': target_domain,
                'api_key': api_key
            }
            
            # Handle special case for commoncrawl (dynamic index URL)
            url = tool_config.get('url', '')
            if tool_config.get('index_url'):
                try:
                    idx_response = requests.get(tool_config['index_url'], timeout=30)
                    if idx_response.status_code == 200:
                        indexes = idx_response.json()
                        if indexes:
                            url = indexes[0]['cdx-api']
                            print(f"[{tool_name}] Using index: {url}")
                except Exception as e:
                    print(f"[{tool_name}] Error getting index: {e}")
                    return
            
            url = substitute_vars(url, variables)
            method = tool_config.get('method', 'GET')
            headers = substitute_vars(tool_config.get('headers', {}), variables)
            params = substitute_vars(tool_config.get('params', {}), variables)
            timeout = tool_config.get('timeout', 30)
            
            # Handle authentication
            auth = None
            auth_config = tool_config.get('auth', {})
            if auth_config.get('type') == 'basic':
                auth_key = get_setting(auth_config.get('setting', ''))
                if auth_key and ':' in auth_key:
                    parts = auth_key.split(':', 1)
                    auth = (parts[0], parts[1])
                else:
                    print(f"[{tool_name}] Invalid auth key format (expected id:secret)")
                    return
            
            all_subdomains = set()
            
            # Make request (with pagination support)
            while url:
                try:
                    response = requests.request(
                        method,
                        url,
                        headers=headers,
                        params=params,
                        auth=auth,
                        timeout=timeout
                    )
                    
                    if response.status_code == 401:
                        print(f"[{tool_name}] Authentication failed")
                        return
                    elif response.status_code == 429:
                        print(f"[{tool_name}] Rate limit exceeded")
                        return
                    elif response.status_code not in [200, 404]:
                        print(f"[{tool_name}] API error: HTTP {response.status_code}")
                        return
                    
                    # Parse response
                    response_type = tool_config.get('response_type', 'json')
                    
                    if response_type == 'json':
                        data = response.json()
                    elif response_type == 'jsonl':
                        # JSON Lines format
                        data = []
                        for line in response.text.strip().split('\n'):
                            if line.strip():
                                try:
                                    data.append(json.loads(line))
                                except:
                                    pass
                    else:
                        data = response.text
                    
                    # Extract subdomains
                    extract_config = tool_config.get('extract', {})
                    subdomains = extract_subdomains_from_response(data, extract_config, target_domain, variables)
                    all_subdomains.update(subdomains)
                    
                    # Handle pagination
                    pagination = tool_config.get('pagination', {})
                    if pagination.get('type') == 'cursor':
                        next_path = pagination.get('next_path', '')
                        parts = next_path.split('.')
                        next_url = data
                        for part in parts:
                            if isinstance(next_url, dict):
                                next_url = next_url.get(part)
                            else:
                                next_url = None
                                break
                        
                        if next_url:
                            url = next_url
                            params = {}
                        else:
                            url = None
                    else:
                        url = None
                    
                except requests.Timeout:
                    print(f"[{tool_name}] Request timeout")
                    return
                except requests.RequestException as e:
                    print(f"[{tool_name}] Request error: {e}")
                    return
            
            print(f"[{tool_name}] Extracted {len(all_subdomains)} unique subdomains")
            
            # Save subdomains
            new_count = 0
            for subdomain in sorted(all_subdomains):
                if is_valid_subdomain(subdomain, target_domain):
                    if save_subdomain(db, subdomain, target_domain, scan_id, tool_name):
                        new_count += 1
                        if new_count % 20 == 0:
                            db.commit()
            
            db.commit()
            print(f"[{tool_name}] Completed: {new_count} new subdomains")
            
        except Exception as e:
            print(f"[{tool_name}] Error: {str(e)}")
            import traceback
            traceback.print_exc()
            db.rollback()
        finally:
            db.close()


def extract_subdomains_from_response(data, extract_config, target_domain, variables):
    """Extract subdomains from API response based on extraction config"""
    subdomains = set()
    extract_type = extract_config.get('type', 'json_path')
    
    if extract_type == 'array':
        subdomains = _extract_array(data, extract_config)
    
    elif extract_type == 'json_path':
        subdomains = _extract_json_path(data, extract_config, variables)
    
    elif extract_type == 'url_extract':
        subdomains = _extract_urls(data, extract_config)
    
    return subdomains


def _extract_array(data, extract_config):
    """Extract from array of objects with specified fields"""
    subdomains = set()
    fields = extract_config.get('fields', [])
    split_newline = extract_config.get('split_on_newline', False)
    strip_wildcard = extract_config.get('strip_wildcard', False)
    
    if isinstance(data, list):
        for item in data:
            for field in fields:
                value = item.get(field, '')
                if value:
                    values = value.split('\n') if split_newline else [value]
                    for v in values:
                        v = v.strip().lower()
                        if strip_wildcard and v.startswith('*.'):
                            v = v[2:]
                        if v:
                            subdomains.add(v)
    
    return subdomains


def _extract_json_path(data, extract_config, variables):
    """Extract using JSON path navigation"""
    subdomains = set()
    path = extract_config.get('path', '')
    subdomain_format = extract_config.get('subdomain_format', '{value}')
    strip_wildcard = extract_config.get('strip_wildcard', False)
    
    # Navigate path
    parts = path.replace('[*]', '').split('.')
    current = data
    
    for part in parts:
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part, [])
        elif isinstance(current, list):
            # Flatten nested lists
            new_current = []
            for item in current:
                if isinstance(item, dict):
                    val = item.get(part, [])
                    if isinstance(val, list):
                        new_current.extend(val)
                    else:
                        new_current.append(val)
            current = new_current
    
    # Process extracted values
    if not isinstance(current, list):
        current = [current] if current else []
    
    for value in current:
        if isinstance(value, str):
            v = value.strip().lower()
            if strip_wildcard and v.startswith('*.'):
                v = v[2:]
            # Apply subdomain format
            variables['value'] = v
            subdomain = substitute_vars(subdomain_format, variables)
            if subdomain:
                subdomains.add(subdomain)
    
    return subdomains


def _extract_urls(data, extract_config):
    """Extract domains from URLs using regex"""
    subdomains = set()
    regex = extract_config.get('regex', r'https?://([^/:?#]+)')
    skip_first = extract_config.get('skip_first', False)
    field = extract_config.get('field')
    
    items = data[1:] if skip_first and isinstance(data, list) else data
    if not isinstance(items, list):
        items = [items]
    
    for item in items:
        url_str = ''
        if field and isinstance(item, dict):
            url_str = item.get(field, '')
        elif isinstance(item, list) and len(item) > 0:
            url_str = item[0]
        elif isinstance(item, str):
            url_str = item
        
        if url_str:
            match = re.search(regex, str(url_str))
            if match:
                domain = match.group(1).strip().lower()
                if ':' in domain:
                    domain = domain.split(':')[0]
                subdomains.add(domain)
    
    return subdomains

