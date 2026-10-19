import argparse
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from .app import create_app


def load_environment(path=None):
    # Explicit path prevents discovery of an unrelated parent directory's .env.
    # Keep passwords containing ${...} literal, and honor existing process values.
    return load_dotenv(Path(path) if path is not None else Path.cwd() / ".env",
                       override=False, interpolate=False, encoding="utf-8-sig")


def main():
    parser = argparse.ArgumentParser(description="SimaX Database Backup local web application")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--env-file", default=None,
                        help="Environment file (default: .env in the working directory)")
    args = parser.parse_args()
    if args.env_file is not None and not Path(args.env_file).is_file():
        parser.error("The specified environment file does not exist or is not a regular file.")
    load_environment(args.env_file)
    uvicorn.run(create_app(args.data_dir), host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
