"""
CLI Tool Executor
Executes command-line tools and parses their output
"""
import subprocess
import os
import sys
import threading
from core.database import SessionLocal
from core.terminal_output import add_output, TerminalOutputCapture
from core.scan_control import check_should_stop
from .common import (
    get_tool_command,
    substitute_vars,
    is_valid_subdomain,
    save_subdomain,
    strip_ansi,
    expand_args_for_execution,
    get_wordlists,
    get_input_files
)


def run_cli_tool(tool_name, tool_config, scan_id, target_domain):
    """Execute a CLI tool and process its output"""
    db = SessionLocal()
    
    # Capture terminal output
    with TerminalOutputCapture(scan_id, tool_name):
        try:
            print(f"[{tool_name}] Starting scan for {target_domain} (scan {scan_id})")
            
            # Get tool command
            command = get_tool_command(tool_config)
            if not command:
                print(f"[{tool_name}] No command configured")
                return
            
            # Build command
            variables = {'domain': target_domain}
            # Add wordlists to variables
            wordlists = get_wordlists()
            variables.update(wordlists)
            # Add input files to variables
            input_files = get_input_files()
            variables.update(input_files)
            
            cmd_parts = command.split()
            args = tool_config.get('args', [])
            # Expand combined option-value pairs (e.g., "-d {domain}" -> ["-d", "{domain}"])
            args = expand_args_for_execution(args)
            args = substitute_vars(args, variables)
            cmd = cmd_parts + args
            
            print(f"[{tool_name}] Executing: {' '.join(cmd)}")
            
            # Execute command
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=8192  # Larger buffer to reduce blocking on high-volume output
                )
            except FileNotFoundError:
                print(f"[{tool_name}] Tool not found: {command}")
                return
            
            # Capture stderr in background thread
            def capture_stderr():
                try:
                    for line in process.stderr:
                        if line.strip():
                            add_output(scan_id, line.rstrip(), 'stderr')
                except:
                    pass
            
            stderr_thread = threading.Thread(target=capture_stderr, daemon=True)
            stderr_thread.start()
            
            output_type = tool_config.get('output', 'lines')
            new_count = 0
            seen = set()
            
            if output_type == 'lines':
                new_count = _process_lines_output(
                    process, tool_name, target_domain, scan_id, db, seen
                )
            
            elif output_type == 'csv':
                new_count = _process_csv_output(
                    process, tool_config, tool_name, target_domain, scan_id, db, seen, variables
                )
            
            # Check if scan should be stopped before waiting
            if check_should_stop(scan_id):
                print(f"[{tool_name}] Stop requested, terminating process...")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                db.commit()
                return
            
            process.wait()
            db.commit()
            
            if process.returncode != 0:
                print(f"[{tool_name}] Process exited with code {process.returncode}")
            
            print(f"[{tool_name}] Completed: {new_count} new subdomains")
            
        except Exception as e:
            print(f"[{tool_name}] Error: {str(e)}")
            db.rollback()
        finally:
            db.close()


def _process_lines_output(process, tool_name, target_domain, scan_id, db, seen):
    """Process line-by-line output from CLI tool"""
    new_count = 0
    line_count = 0
    output_batch_size = 100  # Only add every 100th line to terminal output to reduce lock contention
    
    for line in process.stdout:
        line_count += 1
        
        # Check if scan should be stopped
        if check_should_stop(scan_id):
            print(f"[{tool_name}] Stop requested during output processing")
            break
        
        # Batch terminal output - only capture sample to avoid freezing on high-volume tools
        if line_count % output_batch_size == 0:
            raw_line = line.rstrip()
            if raw_line:
                add_output(scan_id, raw_line, 'stdout')
        
        # Process for subdomains
        line = strip_ansi(line.strip().lower())
        
        if not line or line.startswith('['):
            continue
        
        if line in seen:
            continue
        seen.add(line)
        
        if is_valid_subdomain(line, target_domain):
            if save_subdomain(db, line, target_domain, scan_id, tool_name):
                new_count += 1
                if new_count % 10 == 0:
                    db.commit()
    
    return new_count


def _process_csv_output(process, tool_config, tool_name, target_domain, scan_id, db, seen, variables):
    """Process CSV file output from CLI tool"""
    import csv
    
    # Wait for process to complete
    process.wait()
    
    output_dir = substitute_vars(tool_config.get('output_dir', '.'), variables)
    output_file = substitute_vars(tool_config.get('output_file', ''), variables)
    csv_column = tool_config.get('csv_column', 'subdomain')
    
    csv_path = os.path.join(output_dir, output_file)
    new_count = 0
    
    if os.path.exists(csv_path):
        with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            for row in reader:
                subdomain = None
                # Try multiple column names
                for col in [csv_column, 'Subdomain', 'domain', 'Domain', 'host']:
                    if col in row and row[col]:
                        subdomain = row[col].strip().lower()
                        break
                
                if subdomain and subdomain not in seen:
                    seen.add(subdomain)
                    if is_valid_subdomain(subdomain, target_domain):
                        if save_subdomain(db, subdomain, target_domain, scan_id, tool_name):
                            new_count += 1
                            if new_count % 20 == 0:
                                db.commit()
    else:
        print(f"[{tool_name}] Output file not found: {csv_path}")
    
    return new_count

