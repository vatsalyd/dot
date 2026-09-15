#!/usr/bin/env python3
"""
Simple cross-platform launcher for the unassigned issue bot.

Automatically:
1. Loads environment variables from .env if present.
2. Bootstraps config.yaml from config.example.yaml on first run.
3. Validates required tokens and runs the scan with helpful error messages.

Usage:
    python run.py --dry-run
    python run.py --repo pallets/flask --dry-run
    python run.py
"""

import os
import shutil
import sys


def load_dotenv(dotenv_path: str = ".env") -> dict[str, str]:
    """Lightweight zero-dependency .env loader."""
    loaded = {}
    if not os.path.exists(dotenv_path):
        return loaded

    with open(dotenv_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            # Only set in environment if not already present
            if key not in os.environ:
                os.environ[key] = val
            loaded[key] = val
    return loaded


def bootstrap_config(config_path: str = "config.yaml", example_path: str = "config.example.yaml") -> bool:
    """Creates config.yaml from config.example.yaml if missing and no ad-hoc repo flag is set."""
    if not os.path.exists(config_path) and os.path.exists(example_path):
        shutil.copyfile(example_path, config_path)
        print(f"[*] Initialized '{config_path}' from '{example_path}'.", file=sys.stderr)
        return True
    return False


def run():
    # Allow --help / -h without requiring credentials
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        from main import parse_args
        parse_args()
        return

    # 1. Load .env
    load_dotenv()

    # 2. Check token
    token = os.environ.get("GITHUB_TOKEN")
    if not token or token == "ghp_your_token_here":
        print(
            "ERROR: Missing or placeholder GITHUB_TOKEN.\n"
            "Set GITHUB_TOKEN in your environment or in a .env file (copy .env.example to .env).\n"
            "Create a personal access token at: https://github.com/settings/tokens",
            file=sys.stderr,
        )
        sys.exit(1)

    # 3. Bootstrap config if running default scan without explicit --repo
    has_repo_flag = any(arg == "--repo" or arg.startswith("--repo=") for arg in sys.argv[1:])
    if not has_repo_flag and not os.path.exists("config.yaml"):
        bootstrap_config("config.yaml", "config.example.yaml")

    # 4. Invoke main application directly
    from main import main
    main()


if __name__ == "__main__":
    run()
