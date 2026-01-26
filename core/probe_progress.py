"""
Probe Progress Tracker
Tracks progress of bulk probing operations
"""
import threading
import time
from typing import Dict, Optional
from datetime import datetime, timezone


class ProbeProgressTracker:
    """Thread-safe progress tracker for probe operations"""
    
    def __init__(self):
        self._progress: Dict[str, Dict] = {}
        self._lock = threading.Lock()
    
    def create_job(self, job_id: str, total: int) -> None:
        """Create a new probe job"""
        with self._lock:
            self._progress[job_id] = {
                'total': total,
                'completed': 0,
                'status': 'running',
                'started_at': datetime.now(timezone.utc).isoformat(),
                'completed_at': None
            }
    
    def update_progress(self, job_id: str, completed: int) -> None:
        """Update progress for a job"""
        with self._lock:
            if job_id in self._progress:
                self._progress[job_id]['completed'] = completed
                if completed >= self._progress[job_id]['total']:
                    self._progress[job_id]['status'] = 'completed'
                    self._progress[job_id]['completed_at'] = datetime.now(timezone.utc).isoformat()
    
    def increment_progress(self, job_id: str, increment: int = 1) -> None:
        """Increment progress by a certain amount"""
        with self._lock:
            if job_id in self._progress:
                self._progress[job_id]['completed'] += increment
                if self._progress[job_id]['completed'] >= self._progress[job_id]['total']:
                    self._progress[job_id]['status'] = 'completed'
                    self._progress[job_id]['completed_at'] = datetime.now(timezone.utc).isoformat()
    
    def get_progress(self, job_id: str) -> Optional[Dict]:
        """Get current progress for a job"""
        with self._lock:
            return self._progress.get(job_id)
    
    def complete_job(self, job_id: str) -> None:
        """Mark a job as completed"""
        with self._lock:
            if job_id in self._progress:
                self._progress[job_id]['status'] = 'completed'
                self._progress[job_id]['completed'] = self._progress[job_id]['total']
                self._progress[job_id]['completed_at'] = datetime.now(timezone.utc).isoformat()
    
    def fail_job(self, job_id: str) -> None:
        """Mark a job as failed"""
        with self._lock:
            if job_id in self._progress:
                self._progress[job_id]['status'] = 'failed'
                self._progress[job_id]['completed_at'] = datetime.now(timezone.utc).isoformat()
    
    def delete_job(self, job_id: str) -> None:
        """Delete a job (cleanup)"""
        with self._lock:
            if job_id in self._progress:
                del self._progress[job_id]
    
    def cleanup_old_jobs(self, max_age_seconds: int = 3600) -> None:
        """Remove old completed/failed jobs"""
        with self._lock:
            now = datetime.now(timezone.utc)
            to_delete = []
            for job_id, job_data in self._progress.items():
                if job_data['status'] in ['completed', 'failed'] and job_data.get('completed_at'):
                    completed_at = datetime.fromisoformat(job_data['completed_at'].replace('Z', '+00:00'))
                    age = (now - completed_at).total_seconds()
                    if age > max_age_seconds:
                        to_delete.append(job_id)
            
            for job_id in to_delete:
                del self._progress[job_id]


# Global instance
_progress_tracker = None
_tracker_lock = threading.Lock()


def get_progress_tracker() -> ProbeProgressTracker:
    """Get or create global progress tracker instance"""
    global _progress_tracker
    with _tracker_lock:
        if _progress_tracker is None:
            _progress_tracker = ProbeProgressTracker()
    return _progress_tracker
