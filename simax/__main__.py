import argparse

import uvicorn

from .app import create_app


def main():
    parser = argparse.ArgumentParser(description="SimaX Database Backup local web application")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()
    uvicorn.run(create_app(args.data_dir), host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
