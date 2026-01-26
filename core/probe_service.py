"""
Probe Service
Checks if subdomains are online via DNS, HTTP, and HTTPS
"""
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ProbeService:
    """Service for probing subdomain availability"""
    
    def __init__(self, timeout=8, max_workers=10):
        """
        Initialize probe service
        Args:
            timeout: Timeout in seconds for each probe attempt
            max_workers: Maximum number of concurrent probes
        """
        self.timeout = timeout
        self.max_workers = max_workers
        
        # Create a session with retry strategy for HTTP requests
        self.session = requests.Session()
        retry_strategy = Retry(
            total=1,
            backoff_factor=0.1,
            status_forcelist=[],
            allowed_methods=["GET", "HEAD"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def check_dns(self, subdomain: str) -> bool:
        """
        Check if subdomain resolves via DNS
        Args:
            subdomain: Subdomain to check
        Returns:
            True if DNS resolution succeeds, False otherwise
        """
        try:
            socket.gethostbyname(subdomain)
            return True
        except (socket.gaierror, socket.herror, OSError):
            return False
    
    def check_http(self, subdomain: str) -> Optional[int]:
        """
        Check if subdomain responds to HTTP requests
        Args:
            subdomain: Subdomain to check
        Returns:
            HTTP status code if successful, None otherwise
            Returns 418 if received (will be filtered out in status determination)
        """
        try:
            url = f"http://{subdomain}"
            response = self.session.get(
                url,
                timeout=self.timeout,
                allow_redirects=True,
                verify=False
            )
            return response.status_code
        except (requests.exceptions.RequestException, Exception):
            return None
    
    def check_https(self, subdomain: str) -> Optional[int]:
        """
        Check if subdomain responds to HTTPS requests
        Args:
            subdomain: Subdomain to check
        Returns:
            HTTPS status code if successful, None otherwise
            Returns 418 if received (will be filtered out in status determination)
        """
        try:
            url = f"https://{subdomain}"
            response = self.session.get(
                url,
                timeout=self.timeout,
                allow_redirects=True,
                verify=False
            )
            return response.status_code
        except (requests.exceptions.SSLError, requests.exceptions.RequestException, Exception):
            return None
    
    def probe_subdomain(self, subdomain: str) -> Dict:
        """
        Probe a single subdomain for availability
        Args:
            subdomain: Subdomain to probe
        Returns:
            Dictionary with probe results:
            {
                'status': 'online_http' | 'online_https' | 'online_both' | 'offline' | 'dns_only',
                'dns_resolved': bool,
                'http_status_code': int | None,
                'https_status_code': int | None
            }
        """
        result = {
            'status': 'offline',
            'dns_resolved': False,
            'http_status_code': None,
            'https_status_code': None
        }
        
        # Check DNS first
        dns_resolved = self.check_dns(subdomain)
        result['dns_resolved'] = dns_resolved
        
        if not dns_resolved:
            result['status'] = 'offline'
            return result
        
        # Check HTTP and HTTPS
        http_status = self.check_http(subdomain)
        https_status = self.check_https(subdomain)
        
        result['http_status_code'] = http_status
        result['https_status_code'] = https_status
        
        # Determine final status
        # Filter out 418 (I'm a teapot) - treat as offline
        http_online = http_status is not None and http_status != 418
        https_online = https_status is not None and https_status != 418
        
        if http_online and https_online:
            result['status'] = 'online_both'
        elif http_online:
            result['status'] = 'online_http'
        elif https_online:
            result['status'] = 'online_https'
        elif dns_resolved:
            result['status'] = 'dns_only'
        else:
            result['status'] = 'offline'
        
        return result
    
    def probe_subdomain_batch(self, subdomains: List[str], progress_callback=None) -> Dict[str, Dict]:
        """
        Probe multiple subdomains concurrently
        Args:
            subdomains: List of subdomains to probe
            progress_callback: Optional callback function(current, total) called after each probe completes
        Returns:
            Dictionary mapping subdomain -> probe result
        """
        results = {}
        total = len(subdomains)
        completed = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all probe tasks
            future_to_subdomain = {
                executor.submit(self.probe_subdomain, subdomain): subdomain
                for subdomain in subdomains
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_subdomain):
                subdomain = future_to_subdomain[future]
                try:
                    results[subdomain] = future.result()
                except Exception as e:
                    # If probing fails, mark as offline
                    results[subdomain] = {
                        'status': 'offline',
                        'dns_resolved': False,
                        'http_status_code': None,
                        'https_status_code': None
                    }
                
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)
        
        return results


# Global instance
_probe_service = None


def get_probe_service() -> ProbeService:
    """Get or create global probe service instance"""
    global _probe_service
    if _probe_service is None:
        _probe_service = ProbeService()
    return _probe_service
