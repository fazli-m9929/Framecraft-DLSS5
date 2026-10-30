from __future__ import annotations

import argparse
import json

from .config import get_settings
from .hardware import capabilities


def main() -> None:
    """Parse CLI options and run diagnostics or the local web server.

    Returns:
        None: No value is returned.
    """
    parser = argparse.ArgumentParser(description="Neural Video Studio")
    parser.add_argument(
        "command", choices=["serve", "doctor"],
        nargs="?", default="serve"
    )
    parser.add_argument(
        "--host", default=None,
        help="Bind address, e.g. 127.0.0.1 or 0.0.0.0 (LAN access)"
    )
    parser.add_argument("--port", type=int, default=None, help="Port (default from .env)")
    args = parser.parse_args()
    settings = get_settings()
    if args.command == "doctor":
        print(json.dumps(capabilities(settings), indent=2))
        return
    import uvicorn
    host = args.host or settings.host
    port = args.port or settings.port
    if not (1 <= port <= 65535):
        parser.error("--port must be from 1 to 65535")
    uvicorn.run(
        "nvs.main:app", host=host, port=port,
        workers=1, reload=False
    )


if __name__ == "__main__":
    main()
