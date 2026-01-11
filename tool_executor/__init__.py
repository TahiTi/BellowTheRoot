"""
Tool Executor Package
Runs enumeration tools based on YAML configuration
Supports CLI, API, and Pipeline tool types
"""

from .common import (
    load_tools_config,
    save_tools_config,
    get_tool_config,
    is_tool_enabled,
    get_enabled_tools,
    get_pipeline_tools,
    get_setting,
    get_scan_subdomains,
)

from .cli import run_cli_tool
from .api import run_api_tool
from .pipeline import run_pipeline_tool


def run_tool(tool_name, scan_id, target_domain):
    """Run a tool by name"""
    tool_config = get_tool_config(tool_name)
    
    if not tool_config:
        print(f"[executor] Unknown tool: {tool_name}")
        return
    
    if not tool_config.get('enabled', False):
        print(f"[executor] Tool {tool_name} is disabled, skipping")
        return
    
    tool_type = tool_config.get('type', 'cli')
    
    if tool_type == 'cli':
        run_cli_tool(tool_name, tool_config, scan_id, target_domain)
    elif tool_type == 'api':
        run_api_tool(tool_name, tool_config, scan_id, target_domain)
    elif tool_type == 'pipeline':
        run_pipeline_tool(tool_name, tool_config, scan_id, target_domain)
    else:
        print(f"[executor] Unknown tool type: {tool_type}")


# Export all public functions
__all__ = [
    'load_tools_config',
    'save_tools_config',
    'get_tool_config',
    'is_tool_enabled',
    'get_enabled_tools',
    'get_pipeline_tools',
    'get_setting',
    'get_scan_subdomains',
    'run_tool',
    'run_cli_tool',
    'run_api_tool',
    'run_pipeline_tool',
]

