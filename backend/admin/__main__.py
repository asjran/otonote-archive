"""python -m backend.admin <admin|collector|node|node-worker> --config file.json"""
import argparse
import os

from .config import load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=['admin', 'collector', 'node', 'node-worker'])
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = load_config(args.config, 'node' if args.role == 'node-worker' else args.role)
    os.umask(0o007 if args.role in {'node', 'node-worker'} else 0o077)
    if args.role == 'node-worker':
        from .node import run_worker
        return run_worker(config)
    import uvicorn
    if args.role == 'admin':
        from .app import create_admin
        app = create_admin(config)
    elif args.role == 'collector':
        from .collector import create_collector
        app = create_collector(config)
    else:
        from .node import create_node
        app = create_node(config)
    uvicorn.run(app, host='127.0.0.1', port=config['port'], proxy_headers=False, access_log=False)


if __name__ == '__main__':
    main()
