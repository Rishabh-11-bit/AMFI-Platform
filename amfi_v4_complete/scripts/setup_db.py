"""
AMFI v4 - Database Setup Script
Run: python scripts/setup_db.py

Creates the PostgreSQL database, user, and all tables.
"""
import subprocess
import sys
import os

def run_psql(cmd, password="postgres"):
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    result = subprocess.run(
        ["psql", "-U", "postgres", "-c", cmd],
        env=env, capture_output=True, text=True
    )
    return result.returncode == 0, result.stdout, result.stderr

def main():
    print("\n" + "="*50)
    print("  AMFI v4 - Database Setup")
    print("="*50)

    pg_password = input("\nEnter PostgreSQL 'postgres' user password: ").strip()
    if not pg_password:
        pg_password = "postgres"

    db_password = input("Set password for AMFI database user (default: amfi_password): ").strip()
    if not db_password:
        db_password = "amfi_password"

    print("\nCreating database and user...")

    commands = [
        f"CREATE USER amfi WITH PASSWORD '{db_password}';",
        "CREATE DATABASE amfi_v4;",
        "GRANT ALL PRIVILEGES ON DATABASE amfi_v4 TO amfi;",
        r"\c amfi_v4",
        "GRANT ALL ON SCHEMA public TO amfi;",
    ]

    for cmd in commands:
        ok, out, err = run_psql(cmd, pg_password)
        if not ok and "already exists" not in err:
            if "already exists" in err:
                print(f"  Already exists — OK")
            else:
                print(f"  Warning: {err.strip()}")
        else:
            print(f"  OK: {cmd[:50]}")

    # Update .env
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            content = f.read()
        content = content.replace(
            "postgresql+asyncpg://amfi:amfi_password@localhost:5432/amfi_v4",
            f"postgresql+asyncpg://amfi:{db_password}@localhost:5432/amfi_v4"
        )
        with open(".env", "w") as f:
            f.write(content)
        print(f"\n.env updated with new database password")

    print("\n" + "="*50)
    print("  Database setup complete!")
    print(f"  DB:   amfi_v4")
    print(f"  User: amfi")
    print(f"  Pass: {db_password}")
    print("\n  Run: python run.py")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
