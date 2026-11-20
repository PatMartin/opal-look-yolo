from __future__ import annotations

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m opal_look_yolo")
    parser.add_argument("--env-file")
    parser.add_argument("--no-env-file", action="store_true")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()

    import uvicorn

    from opal_look_yolo import service_control
    from opal_look_yolo.config import Settings, dotenv_baseline
    from opal_look_yolo.dotenv import DotenvError, prepare
    from opal_look_yolo.main import create_app

    try:
        prepare(
            env_file=args.env_file,
            no_env_file=args.no_env_file,
            baseline=dotenv_baseline(),
        )
    except DotenvError as exc:
        parser.error(str(exc))
    settings = Settings()
    if args.host is not None:
        settings.host = args.host
    if args.port is not None:
        settings.port = args.port
    # A restarted child waits for the previous managed server to release
    # the port before binding; then this process becomes the managed one.
    wait_pid = os.environ.get(service_control.WAIT_PID_ENV)
    if wait_pid and wait_pid.isdigit():
        service_control.wait_for_death(int(wait_pid))
    service_control.ensure_pidfile()
    try:
        uvicorn.run(
            create_app(settings=settings),
            host=settings.host,
            port=settings.port,
        )
    finally:
        service_control.release_pidfile()


if __name__ == "__main__":
    main()
