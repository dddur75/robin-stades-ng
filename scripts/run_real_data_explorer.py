from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from robin.capture.real_data_explorer import (  # noqa: E402
    AtomicExplorerStore,
    ExplorerRefreshController,
    GhArtifactClient,
    make_server,
    run_refresh_loop,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Serve the private Robin data explorer")
    result.add_argument("--root", type=Path, required=True)
    result.add_argument("--repository", default="dddur75/robin-stades-ng")
    result.add_argument("--workflow-id", default="321915839")
    result.add_argument("--port", type=int, default=4173)
    result.add_argument("--refresh-seconds", type=int, default=300)
    result.add_argument("--refresh-once", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    store = AtomicExplorerStore(arguments.root)
    client = GhArtifactClient(
        repository=arguments.repository,
        workflow_id=arguments.workflow_id,
    )
    controller = ExplorerRefreshController(store, client)
    if arguments.refresh_once:
        changed = controller.refresh_once()
        print("UPDATED" if changed else "UNCHANGED_OR_UNAVAILABLE")
        return 0 if store.current_pointer() is not None else 2

    if store.current_pointer() is None:
        controller.refresh_once()
    server = make_server(store, port=arguments.port)
    stopped = threading.Event()

    refresh_thread = threading.Thread(
        target=run_refresh_loop,
        args=(controller, stopped, arguments.refresh_seconds),
        kwargs={"refresh_immediately": True},
        name="robin-explorer-refresh",
        daemon=True,
    )
    refresh_thread.start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        server.shutdown()
        server.server_close()
        refresh_thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
