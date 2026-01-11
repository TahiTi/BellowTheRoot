"""
Pipeline Tool Executor
Executes chained command pipelines (e.g., alterx | dnsx)
"""
import subprocess
import tempfile
import os
import time
import threading
from core.database import SessionLocal
from core.terminal_output import add_output, TerminalOutputCapture
from core.scan_control import check_should_stop
from .common import (
    get_tool_command,
    substitute_vars,
    is_valid_subdomain,
    save_subdomain,
    get_scan_subdomains,
    expand_args_for_execution,
    get_wordlists,
    get_input_files
)


def run_pipeline_tool(tool_name, tool_config, scan_id, target_domain):
    """Execute a pipeline tool (multiple commands chained together)"""
    db = SessionLocal()
    temp_file = None
    
    # Background-friendly configuration
    COMMIT_BATCH_SIZE = 25
    BATCH_PAUSE_MS = 50
    
    # Capture terminal output
    with TerminalOutputCapture(scan_id, tool_name):
        try:
            print(f"[{tool_name}] Starting for {target_domain} (scan {scan_id})")
            
            steps = tool_config.get('steps', [])
            if not steps:
                print(f"[{tool_name}] No steps configured")
                return
            
            # Get input subdomains if needed
            input_type = tool_config.get('input')
            if input_type == 'scan_subdomains':
                existing_subdomains = get_scan_subdomains(scan_id)
                if not existing_subdomains:
                    print(f"[{tool_name}] No subdomains found from passive enumeration, skipping")
                    return
                
                print(f"[{tool_name}] Using {len(existing_subdomains)} subdomains as input")
                
                # Write to temp file
                temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
                for subdomain in existing_subdomains:
                    temp_file.write(subdomain + '\n')
                temp_file.close()
            
            variables = {
                'domain': target_domain,
                'input_file': temp_file.name if temp_file else ''
            }
            # Add wordlists to variables
            wordlists = get_wordlists()
            variables.update(wordlists)
            # Add input files to variables
            input_files = get_input_files()
            variables.update(input_files)
            
            # Build pipeline processes
            low_priority = tool_config.get('low_priority', False)
            processes = {}
            
            for i, step in enumerate(steps):
                step_name = step.get('name', f'step{i}')
                command = get_tool_command(step)
                if not command:
                    command = step.get('command', '')
                
                cmd_parts = ['nice', '-n', '15'] if low_priority else []
                cmd_parts.extend(command.split())
                step_args = step.get('args', [])
                # Expand combined option-value pairs (e.g., "-l {input_file}" -> ["-l", "{input_file}"])
                step_args = expand_args_for_execution(step_args)
                cmd_parts.extend(substitute_vars(step_args, variables))
                
                # Determine stdin
                pipe_from = step.get('pipe_from')
                stdin = processes[pipe_from].stdout if pipe_from and pipe_from in processes else None
                
                print(f"[{tool_name}] Step {step_name}: {' '.join(cmd_parts)}")
                
                proc = subprocess.Popen(
                    cmd_parts,
                    stdin=stdin,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=8192  # Larger buffer to reduce blocking on high-volume output
                )
                
                processes[step_name] = proc
                
                # Capture stderr in background thread
                def capture_stderr(proc, step_name):
                    try:
                        for line in proc.stderr:
                            if line.strip():
                                add_output(scan_id, f"[{step_name}] {line.rstrip()}", 'stderr')
                    except:
                        pass
                
                stderr_thread = threading.Thread(target=capture_stderr, args=(proc, step_name), daemon=True)
                stderr_thread.start()
                
                # Close stdout of previous process if piping
                if pipe_from and pipe_from in processes:
                    processes[pipe_from].stdout.close()
            
            # Read output from last step
            last_step = steps[-1]
            last_name = last_step.get('name', f'step{len(steps)-1}')
            output_proc = processes[last_name]
            
            new_count = 0
            # Optimize: Load seen subdomains in chunks to avoid blocking on large datasets
            # For high-volume tools, we'll check against database instead of loading all into memory
            seen = set()
            # Only load a reasonable subset for quick duplicate checking
            # Full duplicate checking happens at database level via upsert
            existing_subdomains = get_scan_subdomains(scan_id)
            if len(existing_subdomains) <= 10000:  # Only load if reasonable size
                seen = set(existing_subdomains)
            else:
                # For large datasets, use empty set and rely on database-level deduplication
                print(f"[{tool_name}] Large dataset detected ({len(existing_subdomains)} subdomains), using database-level deduplication")
            
            # Batch terminal output to reduce lock contention
            output_batch_size = 100  # Only add every 100th line to terminal output
            line_count = 0
            
            for line in output_proc.stdout:
                line_count += 1
                
                # Check if scan should be stopped
                if check_should_stop(scan_id):
                    print(f"[{tool_name}] Stop requested, terminating processes...")
                    # Terminate all processes
                    for proc in processes.values():
                        if proc.poll() is None:
                            proc.terminate()
                    # Wait a bit, then kill if still alive
                    time.sleep(1)
                    for proc in processes.values():
                        if proc.poll() is None:
                            proc.kill()
                    break
                
                # Batch terminal output - only capture sample to avoid freezing
                if line_count % output_batch_size == 0:
                    raw_line = line.rstrip()
                    if raw_line:
                        add_output(scan_id, raw_line, 'stdout')
                
                # Process for subdomains
                subdomain = line.strip().lower()
                
                if not subdomain:
                    continue
                
                # Quick check against seen set (if loaded)
                if seen and subdomain in seen:
                    continue
                
                # Add to seen set to avoid processing duplicates in this batch
                if len(seen) < 100000:  # Limit memory usage
                    seen.add(subdomain)
                
                if is_valid_subdomain(subdomain, target_domain):
                    if save_subdomain(db, subdomain, target_domain, scan_id, tool_name):
                        new_count += 1
                        
                        if new_count % COMMIT_BATCH_SIZE == 0:
                            db.commit()
                            time.sleep(BATCH_PAUSE_MS / 1000.0)
                            
                            if new_count % 100 == 0:
                                print(f"[{tool_name}] Progress: {new_count} new subdomains...")
            
            # Wait for all processes
            for proc in processes.values():
                if proc.poll() is None:
                    proc.wait()
            
            db.commit()
            print(f"[{tool_name}] Completed: {new_count} new subdomains")
            
        except FileNotFoundError as e:
            print(f"[{tool_name}] Tool not found: {e}")
        except Exception as e:
            print(f"[{tool_name}] Error: {str(e)}")
            db.rollback()
        finally:
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except:
                    pass
            db.close()

