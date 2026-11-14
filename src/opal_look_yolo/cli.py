from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

from opal_look_yolo.tree_cmds import register as register_tree_commands

DEFAULT_URL = "http://127.0.0.1:8086"


class RestClient:
    def __init__(
        self,
        base_url: str,
        token: str | None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.token = token
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            transport=transport,
            timeout=30.0,
        )

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = self.client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            _fail({"error": {"code": "connection_failed", "message": str(exc)}})
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {
                    "error": {
                        "code": "http_error",
                        "message": f"Request failed with HTTP {response.status_code}",
                    }
                }
            _fail(payload)
        try:
            return response.json()
        except ValueError:
            return {}


def _fail(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    raise typer.Exit(1)


def _emit(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _client(ctx: typer.Context) -> RestClient:
    return ctx.obj["client"]


def _json_object(raw: str | None, name: str) -> dict[str, Any]:
    if raw is None:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        _fail({"error": {"code": "validation_failed", "message": f"{name} must be JSON"}})
    if not isinstance(value, dict):
        _fail({"error": {"code": "validation_failed", "message": f"{name} must be an object"}})
    return value


def create_cli_app(transport: httpx.BaseTransport | None = None) -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, help="OPAL Look YOLO REST API client")
    info_app = typer.Typer(no_args_is_help=True, help="Service information")
    engines_app = typer.Typer(no_args_is_help=True, help="Engine operations")
    models_app = typer.Typer(no_args_is_help=True, help="Model operations")
    hardware_app = typer.Typer(no_args_is_help=True, help="Hardware operations")

    @app.callback()
    def configure(
        ctx: typer.Context,
        url: str = typer.Option(
            DEFAULT_URL,
            "--url",
            envvar="OPAL_YOLO_URL",
            help="YOLO adapter base URL",
        ),
        token: str | None = typer.Option(
            None,
            "--token",
            envvar="OPAL_YOLO_TOKEN",
            help="Bearer token",
        ),
    ) -> None:
        ctx.obj = {"client": RestClient(url, token, transport=transport)}

    @info_app.command("show")
    def info_show(ctx: typer.Context) -> None:
        _emit(_client(ctx).request("GET", "/api/v1/info/"))

    @info_app.command("health")
    def info_health(ctx: typer.Context) -> None:
        _emit(_client(ctx).request("GET", "/api/v1/health/"))

    @engines_app.command("list")
    def engines_list(ctx: typer.Context) -> None:
        _emit(_client(ctx).request("GET", "/api/v1/engine/"))

    @engines_app.command("discover")
    def engines_discover(ctx: typer.Context) -> None:
        _emit(_client(ctx).request("POST", "/api/v1/engine/discover"))

    @engines_app.command("show")
    def engines_show(
        ctx: typer.Context,
        engine_id: str = typer.Argument("yolo"),
    ) -> None:
        _emit(_client(ctx).request("GET", f"/api/v1/engine/{engine_id}"))

    @engines_app.command("capabilities")
    def engines_capabilities(
        ctx: typer.Context,
        engine_id: str = typer.Argument("yolo"),
    ) -> None:
        _emit(_client(ctx).request("GET", f"/api/v1/engine/{engine_id}/capabilities"))

    @models_app.command("list")
    def models_list(ctx: typer.Context) -> None:
        _emit(_client(ctx).request("GET", "/api/v1/model/"))

    @models_app.command("show")
    def models_show(ctx: typer.Context, model_id: str) -> None:
        _emit(_client(ctx).request("GET", f"/api/v1/model/{model_id}"))

    @models_app.command("load")
    def models_load(
        ctx: typer.Context,
        model_id: str,
        device: str | None = typer.Option(None, "--device"),
    ) -> None:
        payload = {"device": device} if device else {}
        _emit(_client(ctx).request("POST", f"/api/v1/model/{model_id}/load", json=payload))

    @models_app.command("unload")
    def models_unload(ctx: typer.Context, model_id: str) -> None:
        _emit(_client(ctx).request("POST", f"/api/v1/model/{model_id}/unload"))

    @hardware_app.command("list")
    def hardware_list(ctx: typer.Context) -> None:
        _emit(_client(ctx).request("GET", "/api/v1/hardware/"))

    @hardware_app.command("show")
    def hardware_show(ctx: typer.Context, device_id: str) -> None:
        _emit(_client(ctx).request("GET", f"/api/v1/hardware/{device_id}"))

    @app.command("predict")
    def predict(
        ctx: typer.Context,
        source: str,
        model_id: str = typer.Option(..., "--model-id"),
        confidence: float = typer.Option(0.25, "--confidence", min=0.0, max=1.0),
        device: str | None = typer.Option(None, "--device"),
        engine_options: str | None = typer.Option(None, "--engine-options"),
        include_native: bool = typer.Option(False, "--include-native"),
    ) -> None:
        payload = {
            "engine": "yolo",
            "model_id": model_id,
            "source": source,
            "confidence": confidence,
            "device": device,
            "engine_options": _json_object(engine_options, "engine_options") or None,
            "include_native": include_native,
        }
        _emit(_client(ctx).request("POST", "/api/v1/predict", json=payload))

    @app.command("predict-frame")
    def predict_frame(
        ctx: typer.Context,
        image: Annotated[Path, typer.Option("--image", exists=True, readable=True)],
        frame: str = typer.Option(..., "--frame", help="Frame envelope JSON object"),
        model_id: str = typer.Option(..., "--model-id"),
        confidence: float = typer.Option(0.25, "--confidence", min=0.0, max=1.0),
        device: str | None = typer.Option(None, "--device"),
        engine_options: str | None = typer.Option(None, "--engine-options"),
        include_native: bool = typer.Option(False, "--include-native"),
    ) -> None:
        media_type = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
        files = {"image": (image.name, image.read_bytes(), media_type)}
        data: dict[str, str] = {
            "frame": frame,
            "model_id": model_id,
            "confidence": str(confidence),
            "include_native": str(include_native).lower(),
        }
        if device:
            data["device"] = device
        if engine_options:
            data["engine_options"] = engine_options
        _emit(
            _client(ctx).request(
                "POST",
                "/api/v1/predict/frame",
                files=files,
                data=data,
            )
        )

    app.add_typer(info_app, name="info")
    app.add_typer(engines_app, name="engines")
    app.add_typer(models_app, name="models")
    app.add_typer(hardware_app, name="hardware")
    register_tree_commands(app, "opal-yolo")
    return app


app = create_cli_app()


def main() -> None:
    app()
