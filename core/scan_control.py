"""
Scan Control
Manages scan stop requests and tracking
"""
import threading

# In-memory set of scan IDs that should be stopped
_stop_requests = set()
_lock = threading.Lock()


def request_stop(scan_id):
    """
    Request that a scan be stopped
    Args:
        scan_id: The scan ID to stop
    """
    with _lock:
        _stop_requests.add(scan_id)


def check_should_stop(scan_id):
    """
    Check if a scan should be stopped
    Args:
        scan_id: The scan ID to check
    Returns:
        True if the scan should be stopped, False otherwise
    """
    with _lock:
        return scan_id in _stop_requests


def clear_stop_request(scan_id):
    """
    Clear a stop request for a scan (after it has been stopped)
    Args:
        scan_id: The scan ID to clear
    """
    with _lock:
        _stop_requests.discard(scan_id)
