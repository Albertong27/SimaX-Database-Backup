import argparse
import os
from pathlib import Path

import uvicorn
from dotenv import dotenv_values, unset_key

from .app import create_app
from .db import Store
from .service import acquire_runtime_lock


def migrate_credentials(directory, env_file):
    """Explicit one-time import; never inject private values into os.environ."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = acquire_runtime_lock(directory)
    try:
        values = dotenv_values(env_file, interpolate=False, encoding="utf-8-sig")
        secrets = {key: value for key, value in values.items() if key.startswith("SIMAX_SECRET_")}
        store = Store(directory, legacy_secrets=secrets)
        # Retain otherwise unused legacy secrets, encrypted, before removing their file entries.
        try:
            imported = store.get("settings", "imported-secrets")["values"]
        except LookupError:
            imported = {}
        store.put("settings", {"id": "imported-secrets", "values": {**imported, **secrets}})
        for key in secrets:
            unset_key(env_file, key, encoding="utf-8-sig")
        return len(secrets)
    finally:
        lock.close()


def main():
    parser = argparse.ArgumentParser(description="SimaX Database Backup local web application")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default=os.environ.get("SIMAX_DATA_DIR", "data"))
    parser.add_argument("--migrate-env-file", help="Import legacy credentials, remove imported secret entries, and exit (stop SimaX first)")
    args = parser.parse_args()
    if args.migrate_env_file:
        if not Path(args.migrate_env_file).is_file():
            parser.error("The specified migration file does not exist.")
        count = migrate_credentials(args.data_dir, args.migrate_env_file)
        print(f"Encrypted credential migration completed; removed {count} imported secret entries from the environment file.")
        return
    uvicorn.run(create_app(args.data_dir), host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
