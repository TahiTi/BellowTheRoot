"""
Terminal Output Capture
Captures stdout/stderr from tool execution for display in the UI
"""
import threading
from collections import deque
from datetime import datetime

# In-memory store for terminal output per scan
# Format: {scan_id: deque([{'timestamp': datetime, 'line': str, 'type': 'stdout'|'stderr'}])}
_terminal_outputs = {}
_max_lines_per_scan = 10000  # Keep last 10k lines per scan
_lock = threading.Lock()


def add_output(scan_id, line, output_type='stdout'):
    """
    Add a line of output to the terminal output for a scan
    Args:
        scan_id: The scan ID
        line: The output line (without newline)
        output_type: 'stdout' or 'stderr'
    """
    if not line:
        return
    
    with _lock:
        if scan_id not in _terminal_outputs:
            _terminal_outputs[scan_id] = deque(maxlen=_max_lines_per_scan)
        
        _terminal_outputs[scan_id].append({
            'timestamp': datetime.now().isoformat(),
            'line': line,
            'type': output_type
        })


def get_output(scan_id, since_timestamp=None):
    """
    Get terminal output for a scan
    Args:
        scan_id: The scan ID
        since_timestamp: Optional ISO timestamp to get only lines after this time
    Returns:
        List of output lines with timestamps
    """
    with _lock:
        if scan_id not in _terminal_outputs:
            return []
        
        output = list(_terminal_outputs[scan_id])
        
        if since_timestamp:
            # Filter to only lines after the timestamp
            try:
                since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
                output = [
                    line for line in output
                    if datetime.fromisoformat(line['timestamp'].replace('Z', '+00:00')) > since_dt
                ]
            except:
                pass
        
        return output


def clear_output(scan_id):
    """Clear terminal output for a scan"""
    with _lock:
        if scan_id in _terminal_outputs:
            del _terminal_outputs[scan_id]


class TerminalOutputCapture:
    """
    Context manager to capture stdout/stderr and redirect to terminal output store
    """
    def __init__(self, scan_id, tool_name):
        self.scan_id = scan_id
        self.tool_name = tool_name
        self.original_stdout = None
        self.original_stderr = None
        
    def __enter__(self):
        import sys
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        
        # Only replace stdout/stderr if we're not already inside another TerminalOutputCapture
        # This prevents double capture when nested
        if not isinstance(sys.stdout, TerminalOutputCapture):
            sys.stdout = self
            sys.stderr = self
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        import sys
        # Only restore if we actually replaced them
        if sys.stdout is self:
            sys.stdout = self.original_stdout
        if sys.stderr is self:
            sys.stderr = self.original_stderr
    
    def write(self, text):
        """Write to both original stdout and terminal output store"""
        if not text:
            return
        
        # Write to original stdout (which might be another TerminalOutputCapture or real stdout)
        if self.original_stdout:
            self.original_stdout.write(text)
            self.original_stdout.flush()
        
        # Only capture for terminal output if we're the outermost capture
        # (i.e., if original_stdout is not another TerminalOutputCapture)
        # This prevents double capture when nested
        if not isinstance(self.original_stdout, TerminalOutputCapture):
            for line in text.split('\n'):
                if line.strip():
                    add_output(self.scan_id, line, 'stdout')
    
    def flush(self):
        """Flush original stdout"""
        if self.original_stdout:
            self.original_stdout.flush()
