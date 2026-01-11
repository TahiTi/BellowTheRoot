"""
Scan Orchestrator
Manages the execution of enumeration tools based on YAML configuration
Runs tools sequentially (one after another)
Pipeline tools (like active_enum) run in a separate process for isolation
"""
import threading
import multiprocessing
from datetime import datetime, timezone
from .database import SessionLocal
from .database import Scan, ScanSubdomain
from .terminal_output import TerminalOutputCapture, add_output
from .scan_control import check_should_stop, clear_stop_request
from tool_executor import (
    load_tools_config, 
    get_enabled_tools, 
    get_pipeline_tools,
    run_tool,
    is_tool_enabled
)


def start_orchestrated_scan(scan_id, target_domain):
    """
    Start an orchestrated scan that runs all enabled tools
    Args:
        scan_id: The scan ID to execute
        target_domain: The target domain to scan
    """
    thread = threading.Thread(
        target=run_orchestrated_scan,
        args=(scan_id, target_domain),
        daemon=True
    )
    thread.start()


def update_scan_progress(scan_id, current_tool, completed_tools):
    """Update scan progress in database"""
    db = SessionLocal()
    try:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if scan:
            scan.current_tool = current_tool
            scan.completed_tools = completed_tools
            db.commit()
    except Exception as e:
        print(f"[orchestrator] Error updating progress: {str(e)}")
    finally:
        db.close()


def run_orchestrated_scan(scan_id, target_domain):
    """
    Execute all enabled enumeration tools sequentially and manage scan lifecycle
    Args:
        scan_id: The scan ID to execute
        target_domain: The target domain to scan
    """
    db = SessionLocal()
    
    # Capture orchestrator output
    with TerminalOutputCapture(scan_id, 'orchestrator'):
        try:
            # Get enabled tools from YAML config
            enabled_tools = get_enabled_tools()
            pipeline_tools = get_pipeline_tools()
            
            total_tools = len(enabled_tools) + len(pipeline_tools)
            
            if total_tools == 0:
                print(f"[orchestrator] No tools enabled for scan {scan_id}, marking as failed")
                scan = db.query(Scan).filter(Scan.id == scan_id).first()
                if scan:
                    scan.status = 'failed'
                    scan.completed_at = datetime.now(timezone.utc)
                    db.commit()
                return
            
            print(f"[orchestrator] Starting scan {scan_id} for {target_domain}")
            print(f"[orchestrator] Individual tools: {', '.join(enabled_tools)}")
            if pipeline_tools:
                print(f"[orchestrator] Pipeline tools: {', '.join(pipeline_tools)}")
            print(f"[orchestrator] Running tools sequentially...")
            
            # Update scan status to running and set total tools
            scan = db.query(Scan).filter(Scan.id == scan_id).first()
            if scan:
                scan.status = 'running'
                scan.total_tools = total_tools
                scan.completed_tools = 0
                scan.current_tool = None
                db.commit()
            
            # Run each enabled passive tool SEQUENTIALLY
            completed_count = 0
            
            for tool_name in enabled_tools:
                # Check if scan should be stopped
                if check_should_stop(scan_id):
                    print(f"[orchestrator] Stop request detected, stopping scan {scan_id}...")
                    # Clear current tool progress
                    update_scan_progress(scan_id, None, completed_count)
                    break
                
                update_scan_progress(scan_id, tool_name, completed_count)
                print(f"[orchestrator] [{completed_count + 1}/{total_tools}] Running {tool_name}...")
                
                try:
                    run_tool(tool_name, scan_id, target_domain)
                except Exception as e:
                    print(f"[orchestrator] Error running {tool_name}: {str(e)}")
                
                # Check again after tool execution
                if check_should_stop(scan_id):
                    print(f"[orchestrator] Stop request detected after {tool_name}, stopping scan {scan_id}...")
                    # Clear current tool progress
                    update_scan_progress(scan_id, None, completed_count)
                    break
                
                completed_count += 1
                print(f"[orchestrator] [{completed_count}/{total_tools}] {tool_name} completed")
            
            print(f"[orchestrator] All {completed_count} individual tools completed for scan {scan_id}")
            
            # Run pipeline tools (like active_enum) in separate processes for isolation
            for tool_name in pipeline_tools:
                # Check if scan should be stopped
                if check_should_stop(scan_id):
                    print(f"[orchestrator] Stop request detected, stopping scan {scan_id}...")
                    # Clear current tool progress
                    update_scan_progress(scan_id, None, completed_count)
                    break
                
                update_scan_progress(scan_id, tool_name, completed_count)
                print(f"[orchestrator] [{completed_count + 1}/{total_tools}] Running {tool_name} (pipeline, separate process)...")
                
                try:
                    # Run in a separate process for better isolation
                    process = multiprocessing.Process(
                        target=run_tool,
                        args=(tool_name, scan_id, target_domain),
                        daemon=True
                    )
                    process.start()
                    
                    # Wait for completion, checking for stop request
                    while process.is_alive():
                        if check_should_stop(scan_id):
                            print(f"[orchestrator] Stop requested, terminating {tool_name}...")
                            process.terminate()
                            process.join(timeout=5)
                            if process.is_alive():
                                process.kill()
                            # Clear current tool progress
                            update_scan_progress(scan_id, None, completed_count)
                            break
                        process.join(timeout=5)
                    
                except Exception as e:
                    print(f"[orchestrator] Error running {tool_name}: {str(e)}")
                
                # Check again after tool execution
                if check_should_stop(scan_id):
                    print(f"[orchestrator] Stop request detected after {tool_name}, stopping scan {scan_id}...")
                    # Clear current tool progress
                    update_scan_progress(scan_id, None, completed_count)
                    break
                
                completed_count += 1
                print(f"[orchestrator] [{completed_count}/{total_tools}] {tool_name} completed")
            
            # Check if scan was stopped
            if check_should_stop(scan_id):
                # Print messages (they'll be captured by TerminalOutputCapture)
                # Don't use add_output() here to avoid duplicates
                print(f"[orchestrator] Stop request detected for scan {scan_id}")
                print(f"[orchestrator] Scan {scan_id} successfully stopped by user")
                
                # Update scan status to stopped and clear current tool
                # (Status may already be set by API, but we ensure it's correct)
                scan = db.query(Scan).filter(Scan.id == scan_id).first()
                if scan:
                    scan.status = 'stopped'
                    scan.current_tool = None  # Clear current tool
                    scan.completed_tools = completed_count  # Update completed count
                    if not scan.completed_at:
                        scan.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    
                    # Print status messages (will be captured)
                    print(f"[orchestrator] Scan {scan_id} status confirmed as 'stopped'")
                    print(f"[orchestrator] Scan stopped after completing {completed_count}/{total_tools} tools")
                
                clear_stop_request(scan_id)
                # Flush output to ensure messages are captured
                import sys
                import time
                if hasattr(sys.stdout, 'flush'):
                    sys.stdout.flush()
                # Delay to ensure messages are captured and available for streaming
                time.sleep(0.3)
                return
            
            # Clear current tool when done
            update_scan_progress(scan_id, None, completed_count)
            print(f"[orchestrator] All enumeration completed for scan {scan_id}")
            
        except Exception as e:
            print(f"[orchestrator] Error in orchestrated scan: {str(e)}")
            try:
                scan = db.query(Scan).filter(Scan.id == scan_id).first()
                if scan:
                    scan.status = 'failed'
                    scan.completed_at = datetime.now(timezone.utc)
                    db.commit()
            except:
                pass
        finally:
            db.close()
    
    # Finalize the scan in a fresh session
    finalize_scan(scan_id)


def finalize_scan(scan_id):
    """
    Finalize a scan by updating subdomain count and marking as completed
    Args:
        scan_id: The scan ID to finalize
    """
    db = SessionLocal()
    try:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if scan:
            # Don't finalize if scan was stopped
            if scan.status == 'stopped':
                return
            
            # Update subdomain count using optimized COUNT query
            # This is much faster than loading all ScanSubdomain objects
            from sqlalchemy import func
            scan.subdomain_count = db.query(func.count(ScanSubdomain.id)).filter(
                ScanSubdomain.scan_id == scan_id
            ).scalar() or 0
            
            # Mark as completed
            scan.status = 'completed'
            if not scan.completed_at:
                scan.completed_at = datetime.now(timezone.utc)
            
            db.commit()
            print(f"[orchestrator] Scan {scan_id} finalized: {scan.subdomain_count} subdomains found")
    except Exception as e:
        print(f"[orchestrator] Error finalizing scan: {str(e)}")
        db.rollback()
    finally:
        db.close()
