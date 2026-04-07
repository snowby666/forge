"""Entry point for `python -m forge_web`."""

import argparse


def main():
    import uvicorn

    p = argparse.ArgumentParser(description="Forge Web API server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=3001)
    args = p.parse_args()
    uvicorn.run("forge_web:app", host=args.host, port=args.port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
