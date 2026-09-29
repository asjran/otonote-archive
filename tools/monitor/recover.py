#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from collect import load_config, recover_database


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore the monitor database from its last valid backup")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = load_config(Path(args.config))
    database = Path(config["paths"]["database"])
    backup = Path(config["paths"].get("backup", str(database) + ".backup"))
    restored = recover_database(database, backup)
    print(json.dumps({"status": "restored" if restored else "healthy", "database": str(database)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
