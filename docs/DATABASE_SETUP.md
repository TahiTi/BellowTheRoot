# Database Setup Guide

This guide will help you set up the PostgreSQL database for BellowTheRoot.

## Prerequisites

- PostgreSQL installed and running
- Access to create databases (typically requires `postgres` user or sudo access)

## Quick Setup (Automated)

### Python Setup Script (Recommended)

The recommended way to set up the database is using the Python setup script:

```bash
python3 scripts/setup_database.py
```

or make it executable and run directly:

```bash
chmod +x scripts/setup_database.py
./scripts/setup_database.py
```

The script will:
1. **Prompt for database credentials** - You can either:
   - Use credentials from your `.env` file (if it exists)
   - Enter custom database credentials interactively (requires an account with password auhtentication and CREATEDB permissions)
2. **Check database connectivity** - Verifies connection to PostgreSQL
3. **Check database existence** - Confirms the database exists
4. **Initialize database tables** - Creates all required tables:
   - `projects`
   - `scans`
   - `subdomains`
   - `scan_subdomains`
   - `settings`
5. **Run migrations** - Applies any legacy schema migrations
6. **Set up indexes** - Creates performance indexes for faster queries
7. **Enable extensions** - Sets up PostgreSQL extensions (e.g., `pg_trgm` for full-text search)
8. **Verify setup** - Confirms all tables were created successfully
9. **Show statistics** - Displays database statistics and table information

#### Interactive Credential Input

When you run the script, you'll be prompted to either:
- **Use `.env` file**: If a `.env` file exists with `DATABASE_URL`, the script will show you the connection details and ask if you want to use them
- **Enter custom credentials**: You can manually enter:
  - Database host (default: `localhost`)
  - Database port (default: `5432`)
  - Database name (default: `subdomain_enum`)
  - Database user (default: `postgres`)
  - Database password (hidden input)

#### Example Output

```
============================================================
  BellowTheRoot Database Setup
============================================================

============================================================
  Database Configuration
============================================================

ℹ Found .env file with database configuration.
ℹ Database: subdomain_enum
ℹ Host: localhost:5432
ℹ User: myuser
ℹ Password: [hidden]

Use credentials from .env file? [Y/n]: y
ℹ Using credentials from .env file

============================================================
  Checking Database Connection
============================================================

✓ Connected to database
ℹ PostgreSQL version: PostgreSQL 15.3
...
```

### Bash Setup Script (Alternative)

Alternatively, you can use the bash script to create the database and user:

```bash
chmod +x scripts/setup_database.sh
./scripts/setup_database.sh
```

This script will:
1. Check if PostgreSQL is installed
2. Prompt for database name, user, and password
3. Create the database and user
4. Set up proper permissions
5. Display the connection string for your `.env` file

**Note**: After running the bash script, you still need to initialize the database tables using the Python script or by starting the application.

## Manual Setup

### Step 1: Install PostgreSQL (if not already installed)

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**CentOS/RHEL:**
```bash
sudo yum install postgresql-server postgresql-contrib
sudo postgresql-setup initdb
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**macOS:**
```bash
brew install postgresql
brew services start postgresql
```

### Step 2: Connect to PostgreSQL

```bash
sudo -u postgres psql
```

### Step 3: Create Database and User

In the PostgreSQL prompt, run:

```sql
-- Create a new user
CREATE USER subdomain_user WITH PASSWORD 'your_secure_password';

-- Create the database
CREATE DATABASE subdomain_enum OWNER subdomain_user;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE subdomain_enum TO subdomain_user;

-- Connect to the new database
\c subdomain_enum

-- Grant schema privileges
GRANT ALL ON SCHEMA public TO subdomain_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO subdomain_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO subdomain_user;

-- Exit
\q
```

### Step 4: Configure Environment Variables

Create a `.env` file in the project root:

```bash
# Database configuration
DATABASE_URL=postgresql://subdomain_user:your_secure_password@localhost:5432/subdomain_enum

# Flask configuration
SECRET_KEY=your-secret-key-here-change-in-production
DEBUG=False

# Subfinder configuration (optional)
SUBFINDER_PATH=subfinder
```

**Important:** Replace:
- `your_secure_password` with the password you set in Step 3
- `your-secret-key-here-change-in-production` with a secure random string

### Step 5: Initialize Database Tables

You have three options to initialize the database tables:

**Option 1: Use the Python setup script (Recommended)**
```bash
python3 scripts/setup_database.py
```

**Option 2: Tables will be created automatically when you first run the application:**
```bash
python3 app.py
```

**Option 3: Initialize manually using Python:**
```bash
python3 -c "from app import app; from core.database import setup_database; app.app_context().push(); setup_database()"
```

## Verify Database Setup

You can verify the setup by connecting to the database:

```bash
psql -U subdomain_user -d subdomain_enum -h localhost
```

Then check if tables exist:

```sql
\dt
```

You should see the following tables:
- `projects`
- `scans`
- `subdomains`
- `scan_subdomains`
- `settings`

## Using the Python Setup Script

The Python setup script (`scripts/setup_database.py`) provides a comprehensive database initialization solution. Here are some key features:

### Features

- **Interactive credential input**: Choose to use `.env` file or enter custom credentials
- **Automatic table creation**: Creates all required tables automatically
- **Migration support**: Handles legacy schema migrations
- **Index creation**: Sets up performance indexes for optimal query speed
- **Extension management**: Enables PostgreSQL extensions like `pg_trgm` for full-text search
- **Verification**: Confirms all tables were created successfully
- **Statistics**: Shows database statistics after setup

### Credential Options

1. **Using `.env` file**: 
   - If you have a `.env` file with `DATABASE_URL` set, the script will detect it
   - It will show you the connection details (without password) and ask for confirmation
   - Example `.env` entry:
     ```bash
     DATABASE_URL=postgresql://username:password@localhost:5432/subdomain_enum
     ```

2. **Custom credentials**:
   - Enter database host, port, name, user, and password interactively
   - Defaults are provided for convenience (press Enter to use defaults)
   - Password input is hidden for security

### What Gets Created

The script creates the following database structure:

- **Tables**:
  - `projects` - Project management
  - `scans` - Scan records and status
  - `subdomains` - Unique subdomain records
  - `scan_subdomains` - Links between scans and subdomains
  - `settings` - Application settings

- **Indexes**: Performance indexes on frequently queried columns
- **Extensions**: PostgreSQL extensions for advanced features

## Troubleshooting

### Python Script Issues

**"ModuleNotFoundError: No module named 'core'"**
- Make sure you're running the script from the project root directory
- Or use: `python3 -m scripts.setup_database` (if run from project root)

**"Failed to connect to database"**
- Verify PostgreSQL is running: `sudo systemctl status postgresql`
- Check your credentials are correct
- Ensure the database exists (create it first if needed)

**"Password cannot be empty"**
- The script requires a password for security
- If you need a passwordless connection, configure PostgreSQL authentication accordingly

### "peer authentication failed"

If you get authentication errors, you may need to configure PostgreSQL authentication. Edit `/etc/postgresql/*/main/pg_hba.conf`:

```
# Change this line:
local   all             all                                     peer

# To:
local   all             all                                     md5
```

Then restart PostgreSQL:
```bash
sudo systemctl restart postgresql
```

### "permission denied"

Make sure you're running the setup commands as the `postgres` user or with sudo:
```bash
sudo -u postgres psql
```

### "database does not exist"

Double-check the database name in your `.env` file matches what you created.

### Connection refused

Ensure PostgreSQL is running:
```bash
sudo systemctl status postgresql
```

If it's not running:
```bash
sudo systemctl start postgresql
```

### "database does not exist" when using Python script

If the Python script reports that the database doesn't exist:
1. Create the database first using the bash script or manually
2. Or use a PostgreSQL superuser account that can create databases
3. The script will continue even if the database check fails, but the database must exist before table creation

### Using Custom Credentials

When entering custom credentials in the Python script:
- Make sure the database user has sufficient privileges to create tables and indexes
- The database must already exist (the script doesn't create databases, only tables)
- Use the bash script first if you need to create the database and user



