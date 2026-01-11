# BellowTheRoot Settings Documentation

This document provides a comprehensive explanation of all settings available in BellowTheRoot.

---

## Table of Contents

1. [Settings Management](#settings-management)
2. [Individual Tools](#individual-tools)
3. [Pipelines](#pipelines)
4. [API Keys](#api-keys)
5. [Wordlist Files](#wordlist-files)
6. [Input Files](#input-files)
7. [Full YAML Configuration](#full-yaml-configuration)
8. [Danger Zone](#danger-zone)

---

## Settings Management

**Location:** Top section of Settings page

### Import Settings
- **Purpose:** Import a complete configuration from a YAML file
- **Format:** YAML file containing tools configuration and API keys
- **Use Case:** Restore settings from backup, share configurations, or migrate between instances
- **How it works:** 
  - Click "Import Settings" button
  - Select a `.yaml` or `.yml` file
  - The file should contain both `tools.yaml` structure and API keys
  - All existing settings will be replaced with imported values

### Export Settings
- **Purpose:** Export current configuration to a YAML file
- **Format:** YAML file containing all tool configurations and API keys
- **Use Case:** Backup settings, share configurations, or migrate to another instance
- **How it works:**
  - Click "Export Settings" button
  - Downloads a YAML file with complete configuration
  - Includes all tool definitions and API keys

---

## Individual Tools

**Location:** Settings → Individual Tools section

Individual tools are CLI and API tools that run independently to discover subdomains.

### Tool Table Columns

1. **Tool:** Name and description of the tool
2. **Type:** 
   - `CLI` - Command-line tool (runs executable)
   - `API` - HTTP API tool (makes web requests)
3. **Status:** Enabled (green) or Disabled (gray)
4. **Actions:**
   - **Enable/Disable:** Toggle tool on/off
   - **Edit:** Open tool configuration editor

### Tool Configuration Fields

When editing a tool, you can configure:

#### For CLI Tools:
- **Name:** Unique identifier (lowercase, alphanumeric, hyphens, underscores)
- **Type:** `cli`
- **Description:** Human-readable description
- **Command:** Executable command (e.g., `subfinder`, `python3 /opt/tool.py`)
- **Args:** List of command-line arguments
  - Use placeholders: `{domain}`, `{wordlist_name}`, `{input_file_name}`
  - Example: `["-d", "{domain}", "-silent"]`
- **Output Type:**
  - `lines` - Line-by-line text output (default)
  - `csv` - CSV file output
- **Path Setting:** (Optional) Database setting key for custom command path
- **Enabled:** Boolean to enable/disable tool

#### For API Tools:
- **Name:** Unique identifier
- **Type:** `api`
- **Description:** Human-readable description
- **Method:** HTTP method (`GET`, `POST`, etc.)
- **URL:** API endpoint URL
  - Use placeholders: `{domain}`, `{api_key}`
- **Headers:** HTTP headers (key-value pairs)
- **Params:** URL query parameters
- **Timeout:** Request timeout in seconds
- **Response Type:** `json`, `jsonl`
- **Extract Configuration:**
  - `type`: How to extract subdomains (`json_path`, `array`, `url_extract`)
  - `path`: JSONPath expression for JSON responses
  - `fields`: Field names for array extraction
  - `regex`: Regular expression for URL extraction
- **API Key Setting:** Database setting key for API key
- **Pagination:** (Optional) Configuration for paginated APIs
- **Enabled:** Boolean to enable/disable tool

### Common Placeholders

- `{domain}` - Target domain (automatically substituted)
- `{api_key}` - API key from settings (for API tools)
- `{wordlist_name}` - Path to wordlist file (from Wordlists section)
- `{input_file_name}` - Path to input file (from Input Files section)

---

## Pipelines

**Location:** Settings → Pipelines section

Pipelines are chained command sequences that run multiple tools in sequence, with output from one tool piped to the next.

### Pipeline Characteristics

- **Execution Order:** Pipelines run **after** all individual tools complete
- **Process Isolation:** Each pipeline runs in a separate process
- **Input Source:** Can use subdomains from previous tools or input files

### Pipeline Configuration Fields

- **Name:** Unique identifier
- **Type:** `pipeline`
- **Description:** Human-readable description
- **Run After:** `passive` (runs after individual tools)
- **Low Priority:** Boolean - if true, runs with `nice -n 15` (lower CPU priority)
- **Input:** 
  - `scan_subdomains` - Uses all subdomains found by previous tools
  - (empty) - No automatic input file
- **Steps:** List of pipeline steps, each with:
  - **name:** Step identifier
  - **command:** Executable command
  - **args:** Command arguments (can use placeholders)
  - **pipe_from:** (Optional) Name of previous step to pipe output from

### Pipeline Example

```yaml
bruteforce_pipeline:
  enabled: true
  type: pipeline
  description: Subdomain bruteforce using alterx permutations + dnsx resolution
  run_after: passive
  low_priority: true
  input: scan_subdomains
  steps:
  - name: alterx
    command: alterx
    args:
    - -l {input_file}
    - -silent
  - name: dnsx
    command: dnsx
    args:
    - -silent
    pipe_from: alterx  # Receives output from alterx step
```

### Pipeline Execution Flow

1. Individual tools run first (if any enabled)
2. If `input: scan_subdomains` is set, creates temp file with all discovered subdomains
3. First step runs with input file (if configured)
4. Each subsequent step receives output from previous step via `pipe_from`
5. Final step's output is processed for subdomains

---

## API Keys

**Location:** Settings → API Keys section

### Purpose
Store API keys for tools that require authentication (SecurityTrails, Censys, VirusTotal, etc.)

### How It Works

- **Automatic Detection:** API keys are automatically detected from tool configurations
- **Display:** Shows all tools that have `api_key_setting` configured
- **Storage:** Stored in database with key format: `tool_<toolname>_api_key`
- **Usage:** Automatically substituted in tool configurations using `{api_key}` placeholder

### Adding/Editing API Keys

1. Find the tool in the API Keys section
2. Enter your API key in the input field
3. API key is saved automatically when you click "Save Settings" (if available) or when you edit the tool

### API Key Security

- **Storage:** API keys are stored in the database
- **Access:** Only accessible through the Settings page
- **Export:** Included in exported settings (be careful when sharing)
- **Best Practice:** Never commit API keys to version control

---

## Wordlist Files

**Location:** Settings → Wordlist Files section

### Purpose
Manage wordlist files that can be referenced in tool configurations.

### How It Works

1. **Add Wordlist:**
   - Click "Add Wordlist" button
   - Enter a name (e.g., `common`, `subdomains`, `dns`)
   - Enter the full file path (e.g., `/opt/wordlists/common.txt`)
   - Saved as setting: `wordlist_<name>`

2. **Use in Tools:**
   - Reference in tool args using: `{wordlist_<name>}`
   - Example: `["-w", "{wordlist_common}"]`
   - Automatically substituted with the file path

3. **Edit/Delete:**
   - Click edit icon to modify name or path
   - Click delete icon to remove wordlist

### Wordlist Naming Convention

- **Setting Key Format:** `wordlist_<name>`
- **Placeholder Format:** `{wordlist_<name>}`
- **Name Rules:** Lowercase, alphanumeric, underscores, hyphens

### Example

```
Wordlist Name: common
File Path: /opt/wordlists/common.txt
Setting Key: wordlist_common
Usage in tool: ["-w", "{wordlist_common}"]
```

---

## Input Files

**Location:** Settings → Input Files section

### Purpose
Manage input files that can be referenced in tool configurations (similar to wordlists but for general input files).

### How It Works

1. **Add Input File:**
   - Click "Add Input File" button
   - Enter a name (e.g., `domains`, `targets`, `yousign`)
   - Enter the full file path (e.g., `/opt/input/domains.txt`)
   - Saved as setting: `input_file_<name>`

2. **Use in Tools:**
   - Reference in tool args using: `{input_file_<name>}`
   - Example: `["-l", "{input_file_yousign}"]`
   - Automatically substituted with the file path

3. **Edit/Delete:**
   - Click edit icon to modify name or path
   - Click delete icon to remove input file

### Input File Naming Convention

- **Setting Key Format:** `input_file_<name>`
- **Placeholder Format:** `{input_file_<name>}`
- **Name Rules:** Lowercase, alphanumeric, underscores, hyphens

### Difference from Wordlists

- **Wordlists:** Typically used for bruteforcing/permutation tools
- **Input Files:** General purpose input files (domains, targets, etc.)
- Both work the same way, but separated for organizational purposes

### Example

```
Input File Name: yousign
File Path: /opt/input/yousign.txt
Setting Key: input_file_yousign
Usage in tool: ["-l", "{input_file_yousign}"]
```

### Special Input File: `{input_file}`

When a pipeline has `input: scan_subdomains`, a temporary file is automatically created with all discovered subdomains. This file path is available as `{input_file}` placeholder.

---

## Full YAML Configuration

**Location:** Settings → Full Configuration (tools.yaml) section

### Purpose
Direct editing of the complete `tools.yaml` configuration file.

### Features

- **Full Access:** Edit all tool configurations in one place
- **YAML Syntax:** Standard YAML format
- **Sync Status:** Shows if YAML is synced with tool table or modified
- **Save Button:** Saves changes to `tools.yaml` file
- **Auto-sync:** Changes in tool table sync to YAML editor

### YAML Structure

```yaml
tools:
  tool_name:
    enabled: true/false
    type: cli/api/pipeline
    description: "Tool description"
    # ... tool-specific fields ...
    
templates:
  cli:
    # CLI tool template
  api:
    # API tool template
```

### Common Placeholders in YAML

- `{domain}` - Target domain
- `{api_key}` - API key from settings
- `{wordlist_<name>}` - Wordlist file path
- `{input_file_<name>}` - Input file path
- `{input_file}` - Auto-generated temp file (pipelines with `input: scan_subdomains`)

### Editing Tips

1. **YAML Syntax:** Use proper indentation (spaces, not tabs)
2. **Quotes:** Use quotes for strings with special characters
3. **Lists:** Use `-` for list items
4. **Validation:** Invalid YAML will show errors
5. **Backup:** Export settings before making major changes

### Sync Behavior

- **Tool Table → YAML:** Changes in tool table automatically update YAML
- **YAML → Tool Table:** Saving YAML reloads tool table
- **Status Indicator:** Shows "Synced" or "Modified" status

---

## Danger Zone

**Location:** Bottom of Settings page (red section)

### Clear All Data

**⚠️ WARNING: This action is irreversible!**

- **Purpose:** Delete all data from the database
- **What gets deleted:**
  - All projects
  - All scans
  - All subdomains
  - All scan-subdomain relationships
  - **Settings are preserved** (tools, API keys, wordlists, input files)
- **Use Case:** 
  - Start fresh with clean database
  - Remove all discovered subdomains
  - Testing/development cleanup
- **Confirmation:** Requires explicit confirmation before execution

### What is NOT Deleted

- Tool configurations (tools.yaml)
- API keys
- Wordlist settings
- Input file settings
- Database schema (tables remain, just emptied)

---

## Settings Storage

### Database Storage

All settings are stored in the `settings` table with:
- **key:** Setting identifier (e.g., `tool_securitytrails_api_key`)
- **value:** Setting value (stored as text)
- **updated_at:** Timestamp of last update

### Setting Key Patterns

- **Tool API Keys:** `tool_<toolname>_api_key`
- **Tool Paths:** `tool_<toolname>_path`
- **Wordlists:** `wordlist_<name>`
- **Input Files:** `input_file_<name>`

### File Storage

- **tools.yaml:** Stored in `config/` directory
- **Backup:** Can be exported/imported via Settings Management

---

## Best Practices

### 1. Tool Configuration
- Use descriptive tool names
- Add clear descriptions
- Test tools individually before enabling
- Use placeholders for flexibility

### 2. API Keys
- Store securely (never commit to git)
- Rotate keys periodically
- Use environment-specific keys
- Export/backup settings regularly

### 3. Wordlists/Input Files
- Use absolute paths
- Verify file paths exist
- Organize with clear naming
- Keep files updated

### 4. Pipelines
- Test steps individually first
- Use `low_priority: true` for resource-intensive pipelines
- Monitor output for errors
- Start with simple pipelines

### 5. YAML Editing
- Backup before major changes
- Validate YAML syntax
- Test after changes
- Use version control for tools.yaml

---

## Troubleshooting

### Tool Not Running
- Check if tool is enabled
- Verify command path is correct
- Check tool logs in terminal output
- Ensure tool is installed and in PATH

### API Key Issues
- Verify API key is correct
- Check API key setting name matches tool config
- Test API key manually
- Check API rate limits

### Placeholder Not Working
- Verify placeholder name matches setting key
- Check spelling (case-sensitive)
- Ensure setting exists in database
- Check tool configuration syntax

### Pipeline Not Executing
- Verify pipeline is enabled
- Check if individual tools found subdomains (if using `input: scan_subdomains`)
- Review pipeline step configuration
- Check terminal output for errors

---

## Advanced Configuration

### Custom Tool Paths

Use `path_setting` in tool config to reference a database setting:

```yaml
tool_name:
  command: {path}
  path_setting: tool_toolname_path
```

Then set `tool_toolname_path` in database with full command path.

### Complex Pipelines

Pipelines can chain multiple tools:

```yaml
complex_pipeline:
  steps:
  - name: step1
    command: tool1
    args: ["-arg", "value"]
  - name: step2
    command: tool2
    args: ["-arg2"]
    pipe_from: step1  # Receives step1 output
  - name: step3
    command: tool3
    pipe_from: step2  # Receives step2 output
```

### API Tool Pagination

For APIs with pagination:

```yaml
api_tool:
  type: api
  pagination:
    type: cursor
    next_path: links.next
  # Tool will automatically follow pagination
```

---

## Summary

The Settings page provides comprehensive control over:
- **Tool Management:** Configure individual tools and pipelines
- **API Integration:** Manage API keys for external services
- **Resource Files:** Organize wordlists and input files
- **Configuration:** Direct YAML editing for advanced users
- **Data Management:** Clear database when needed

All settings are stored persistently and can be exported/imported for backup and migration purposes.
