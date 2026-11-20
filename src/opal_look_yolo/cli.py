from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any

import anyio
import httpx
import typer
from fastapi import FastAPI
from typer.core import TyperGroup

from opal_look_yolo.config import Settings, dotenv_baseline
from opal_look_yolo.dotenv import DotenvError, prepare
from opal_look_yolo.main import create_app
from opal_look_yolo.tree_cmds import register as register_tree_commands

EMBEDDED_BASE_URL = "http://opal-yolo.local"


class _ConnectionFailed(Exception):
    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(payload["error"]["message"])
        self.payload = payload


class RestClient:
    def __init__(
        self,
        base_url: str | None,
        token: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
        service_app: FastAPI | None = None,
    ) -> None:
        self.token = token
        self.base_url = (base_url or EMBEDDED_BASE_URL).rstrip("/")
        self.transport = transport
        self.service_app = service_app
        self.embedded = not base_url and transport is None
        self.last_error: dict[str, Any] | None = None

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._send(method, path, **kwargs)
        except _ConnectionFailed as exc:
            self.last_error = exc.payload["error"]
            _fail(exc.payload)
        return self._parse(response)

    def _parse(self, response: httpx.Response) -> Any:
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
            self.last_error = payload.get("error")
            _fail(payload)
        try:
            return response.json()
        except ValueError:
            return {}

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            return anyio.run(self._request, method, path, headers, kwargs)
        except httpx.HTTPError as exc:
            raise _ConnectionFailed(
                {"error": {"code": "connection_failed", "message": str(exc)}}
            ) from exc

    def etag(self, path: str = "/api/v1/setting/") -> str:
        try:
            response = self._send("GET", path)
        except _ConnectionFailed as exc:
            self.last_error = exc.payload["error"]
            _fail(exc.payload)
        if response.status_code >= 400:
            self.last_error = {"code": "http_error",
                               "message": f"ETag read failed: {response.status_code}"}
            _fail({"error": self.last_error})
        return response.headers.get("ETag", "*")

    def mutate(self, method: str, path: str, etag_path: str | None = None,
               **kwargs: Any) -> Any:
        """Config write guarded by the current ETag of `etag_path`
        (the settings map revision by default)."""
        tag = self.etag(etag_path or "/api/v1/setting/")
        headers = dict(kwargs.pop("headers", {}))
        headers["If-Match"] = tag
        return self.request(method, path, headers=headers, **kwargs)

    async def _request(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        kwargs: dict[str, Any],
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            transport=self._client_transport(),
            timeout=30.0,
        ) as client:
            return await client.request(method, path, headers=headers, **kwargs)

    def _client_transport(self) -> httpx.AsyncBaseTransport | None:
        if not self.embedded:
            return self.transport
        try:
            service = self.service_app or create_app()
        except Exception as exc:
            _fail(
                {
                    "error": {
                        "code": "configuration_failed",
                        "message": f"Embedded YOLO application failed to start: {exc}",
                    }
                }
            )
        return httpx.ASGITransport(app=service)


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


class _PredictGroup(TyperGroup):
    """`predict` is both the /predict command (bare invocation) and the
    group carrying `predict frame` (x-opal-cli dual binding)."""

    def resolve_command(self, ctx, args):
        if args and args[0] in self.commands:
            return super().resolve_command(ctx, args)
        cmd = self.commands.get("run")
        if cmd is None or not args:
            return super().resolve_command(ctx, args)
        return "predict", cmd, args


def create_cli_app(
    transport: httpx.AsyncBaseTransport | None = None,
    service_app: FastAPI | None = None,
    label: str = "opal-yolo",
) -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, help="OPAL Look YOLO REST API client")
    info_app = typer.Typer(no_args_is_help=True, help="Service information")
    engines_app = typer.Typer(no_args_is_help=True, help="Engine operations")
    models_app = typer.Typer(no_args_is_help=True, help="Model operations")
    hardware_app = typer.Typer(no_args_is_help=True, help="Hardware operations")
    predict_app = typer.Typer(
        cls=_PredictGroup,
        no_args_is_help=True,
        help="Predictions (`predict <source>` or `predict frame`)",
    )
    config_app = typer.Typer(no_args_is_help=True, help="Configuration snapshots")
    setting_app = typer.Typer(no_args_is_help=True, help="Settings")
    profile_app = typer.Typer(no_args_is_help=True, help="Portable profiles")
    persona_app = typer.Typer(no_args_is_help=True, help="Persona catalog")
    service_app_typer = typer.Typer(no_args_is_help=True, help="Service lifecycle")

    @app.callback()
    def configure(
        ctx: typer.Context,
        url: str | None = typer.Option(
            None,
            "--url",
            help="Remote YOLO adapter base URL; omit to run embedded ASGI",
        ),
        token: str | None = typer.Option(
            None,
            "--token",
            help="Bearer token",
        ),
        env_file: Annotated[
            Path | None,
            typer.Option("--env-file", help="Load this dotenv file instead of ./.env"),
        ] = None,
        no_env_file: Annotated[
            bool,
            typer.Option("--no-env-file", help="Disable dotenv loading and .env initialization"),
        ] = False,
    ) -> None:
        try:
            prepare(
                env_file=env_file,
                no_env_file=no_env_file,
                baseline=dotenv_baseline(),
            )
        except DotenvError as exc:
            _fail({"error": {"code": "dotenv_error", "message": str(exc)}})
        ctx.obj = {
            "client": RestClient(
                url if url is not None else os.environ.get("OPAL_YOLO_URL"),
                token if token is not None else os.environ.get("OPAL_YOLO_TOKEN"),
                transport=transport,
                service_app=service_app,
            )
        }

    @app.command("serve")
    def serve(
        host: str | None = typer.Option(None, "--host", help="Bind host"),
        port: int | None = typer.Option(None, "--port", min=1, max=65535, help="Bind port"),
    ) -> None:
        import uvicorn

        settings = Settings()
        if host is not None:
            settings.host = host
        if port is not None:
            settings.port = port
        uvicorn.run(create_app(settings=settings), host=settings.host, port=settings.port)

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

    @predict_app.command("run", hidden=True)
    def predict_run(
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

    @predict_app.command("frame")
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

    @setting_app.command("list")
    def setting_list(ctx: typer.Context) -> None:
        _emit(_client(ctx).request("GET", "/api/v1/setting/"))

    @setting_app.command("show")
    def setting_show(ctx: typer.Context, key: str) -> None:
        _emit(_client(ctx).request("GET", f"/api/v1/setting/{key}"))

    @setting_app.command("set")
    def setting_set(ctx: typer.Context, key: str, value: str) -> None:
        _emit(_client(ctx).mutate(
            "PUT", f"/api/v1/setting/{key}", json={"value": json.loads(value)}))

    @setting_app.command("remove")
    def setting_remove(ctx: typer.Context, key: str) -> None:
        _emit(_client(ctx).mutate("DELETE", f"/api/v1/setting/{key}"))

    config_app.add_typer(setting_app, name="setting")

    @config_app.command("save")
    def config_save(
        ctx: typer.Context,
        out: Annotated[Path | None, typer.Option(
            "--out",
            help="Write the snapshot to FILE instead of the managed store.")] = None,
    ) -> None:
        result = _client(ctx).request(
            "POST", "/api/v1/config/save",
            json={"destination": "response" if out else "managed"})
        if out:
            out.write_text(
                json.dumps(result["snapshot"], indent=2) + "\n", encoding="utf-8")
            typer.echo(str(out))
        else:
            _emit(result)

    @config_app.command("load")
    def config_load(
        ctx: typer.Context,
        file: Annotated[Path | None, typer.Option(
            "--in", help="Snapshot file; omit for the managed snapshot.")] = None,
    ) -> None:
        body: dict = {}
        if file:
            body = {"snapshot": json.loads(file.read_text(encoding="utf-8"))}
        _emit(_client(ctx).mutate("POST", "/api/v1/config/load", json=body))

    @config_app.command("validate")
    def config_validate(
        ctx: typer.Context,
        file: Annotated[Path | None, typer.Option(
            "--in", help="Snapshot file; omit to validate the live config.")] = None,
    ) -> None:
        body: dict = {}
        if file:
            body = {"snapshot": json.loads(file.read_text(encoding="utf-8"))}
        _emit(_client(ctx).request("POST", "/api/v1/config/validate", json=body))

    def _profile_fields(name, description, is_active, shared, module,
                        infile, body) -> dict:
        if infile:
            doc = json.loads(Path(infile).read_text(encoding="utf-8"))
            if any(v is not None for v in (name, description, is_active,
                                           shared)) or module or body:
                _fail({"error": {"code": "validation_failed",
                                 "message": "--in is exclusive with the field flags"}})
            return doc
        doc = _json_object(body, "body")
        if name is not None:
            doc["name"] = name
        if description is not None:
            doc["description"] = description
        if is_active is not None:
            doc["is_active"] = is_active
        if shared is not None:
            doc["shared"] = json.loads(Path(shared).read_text(encoding="utf-8"))
        for kv in module or []:
            mod_key, _, val = kv.partition("=")
            if not mod_key or not val:
                _fail({"error": {"code": "validation_failed",
                                 "message": "--module takes KEY=JSON_FILE"}})
            doc.setdefault("modules", {})[mod_key] = json.loads(
                Path(val).read_text(encoding="utf-8"))
        return doc

    _PROFILE_OPTS = dict(
        name=typer.Option(None, "--name"),
        description=typer.Option(None, "--description"),
        is_active=typer.Option(None, "--is-active/--no-is-active"),
        shared=typer.Option(None, "--shared", help="Shared compartment file."),
        module=typer.Option(None, "--module",
                            help="KEY=JSON_FILE module compartment; repeatable."),
        infile=typer.Option(None, "--in", help="Whole profile document file."),
        body=typer.Option(None, "--body", help="Inline JSON body."),
    )

    @profile_app.command("list")
    def profile_list(ctx: typer.Context) -> None:
        _emit(_client(ctx).request("GET", "/api/v1/profile/"))

    @profile_app.command("show")
    def profile_show(ctx: typer.Context, profile_id: str) -> None:
        _emit(_client(ctx).request("GET", f"/api/v1/profile/{profile_id}"))

    @profile_app.command("add")
    def profile_add(
        ctx: typer.Context,
        name: str = _PROFILE_OPTS["name"],
        description: str = _PROFILE_OPTS["description"],
        is_active: bool = _PROFILE_OPTS["is_active"],
        shared: Path = _PROFILE_OPTS["shared"],
        module: list[str] = _PROFILE_OPTS["module"],
        infile: Path = _PROFILE_OPTS["infile"],
        body: str = _PROFILE_OPTS["body"],
    ) -> None:
        doc = _profile_fields(name, description, is_active, shared, module,
                              infile, body)
        _emit(_client(ctx).mutate("POST", "/api/v1/profile/", json=doc))

    @profile_app.command("update")
    def profile_update(
        ctx: typer.Context,
        profile_id: str,
        name: str = _PROFILE_OPTS["name"],
        description: str = _PROFILE_OPTS["description"],
        is_active: bool = _PROFILE_OPTS["is_active"],
        shared: Path = _PROFILE_OPTS["shared"],
        module: list[str] = _PROFILE_OPTS["module"],
        infile: Path = _PROFILE_OPTS["infile"],
        body: str = _PROFILE_OPTS["body"],
    ) -> None:
        doc = _profile_fields(name, description, is_active, shared, module,
                              infile, body)
        item = f"/api/v1/profile/{profile_id}"
        _emit(_client(ctx).mutate("PATCH", item, etag_path=item, json=doc))

    @profile_app.command("remove")
    def profile_remove(ctx: typer.Context, profile_id: str) -> None:
        item = f"/api/v1/profile/{profile_id}"
        _emit(_client(ctx).mutate("DELETE", item, etag_path=item))

    @profile_app.command("activate")
    def profile_activate(ctx: typer.Context, profile_id: str) -> None:
        _emit(_client(ctx).mutate(
            "POST", f"/api/v1/profile/{profile_id}/activate"))

    @persona_app.command("list")
    def persona_list(
        ctx: typer.Context,
        enabled: bool | None = typer.Option(None, "--enabled/--no-enabled"),
    ) -> None:
        q = f"?enabled={str(enabled).lower()}" if enabled is not None else ""
        _emit(_client(ctx).request("GET", "/api/v1/persona/" + q))

    @persona_app.command("add")
    def persona_add(
        ctx: typer.Context,
        persona_id: str = typer.Option(..., "--persona-id"),
        name: str = typer.Option(..., "--name"),
        description: str | None = typer.Option(None, "--description"),
        voice_id: str | None = typer.Option(None, "--voice-id"),
        enabled: bool | None = typer.Option(None, "--enabled/--no-enabled"),
        if_match: str | None = typer.Option(None, "--if-match"),
    ) -> None:
        body = {"persona_id": persona_id, "name": name,
                "description": description, "voice_id": voice_id}
        if enabled is not None:
            body["enabled"] = enabled
        body = {k: v for k, v in body.items() if v is not None}
        if if_match:
            _emit(_client(ctx).request(
                "POST", "/api/v1/persona/", json=body,
                headers={"If-Match": if_match}))
        else:
            _emit(_client(ctx).mutate("POST", "/api/v1/persona/", json=body))

    @persona_app.command("show")
    def persona_show(ctx: typer.Context, persona_id: str) -> None:
        _emit(_client(ctx).request("GET", f"/api/v1/persona/{persona_id}"))

    @persona_app.command("update")
    def persona_update(
        ctx: typer.Context,
        persona_id: str,
        name: str | None = typer.Option(None, "--name"),
        description: str | None = typer.Option(None, "--description"),
        voice_id: str | None = typer.Option(None, "--voice-id"),
        enabled: bool | None = typer.Option(None, "--enabled/--no-enabled"),
        if_match: str | None = typer.Option(None, "--if-match"),
    ) -> None:
        body = {k: v for k, v in {"name": name, "description": description,
                                  "voice_id": voice_id,
                                  "enabled": enabled}.items() if v is not None}
        if not body:
            _fail({"error": {"code": "validation_failed",
                             "message": "no fields supplied"}})
        if if_match:
            _emit(_client(ctx).request(
                "PATCH", f"/api/v1/persona/{persona_id}", json=body,
                headers={"If-Match": if_match}))
        else:
            item = f"/api/v1/persona/{persona_id}"
            _emit(_client(ctx).mutate("PATCH", item, etag_path=item, json=body))

    @persona_app.command("remove")
    def persona_remove(
        ctx: typer.Context,
        persona_id: str,
        if_match: str | None = typer.Option(None, "--if-match"),
    ) -> None:
        if if_match:
            _emit(_client(ctx).request(
                "DELETE", f"/api/v1/persona/{persona_id}",
                headers={"If-Match": if_match}))
        else:
            item = f"/api/v1/persona/{persona_id}"
            _emit(_client(ctx).mutate("DELETE", item, etag_path=item))

    @persona_app.command("validate")
    def persona_validate(ctx: typer.Context, persona_id: str) -> None:
        _emit(_client(ctx).request(
            "POST", f"/api/v1/persona/{persona_id}/validate"))

    def _rest_or_fallback(ctx: typer.Context, method: str, path: str,
                          **kwargs) -> Any | None:
        """REST call; None when the server cannot be reached at all."""
        client = _client(ctx)
        try:
            response = client._send(method, path, **kwargs)
        except _ConnectionFailed as exc:
            client.last_error = exc.payload["error"]
            return None
        return client._parse(response)

    @service_app_typer.command("start")
    def service_start(
        ctx: typer.Context,
        append: bool = typer.Option(False, "--append",
                                    help="Append to the service log."),
        port: int | None = typer.Option(None, "--port"),
        host: str | None = typer.Option(None, "--host"),
        data_dir: str | None = typer.Option(None, "--data-dir"),
    ) -> None:
        """Start the managed server (restart when one is already running)."""
        resp = _rest_or_fallback(ctx, "POST", "/api/v1/service/start",
                                 json={"append": append})
        if resp is not None:
            _emit(resp)
            return
        # Local fallback: the server is down — spawn it directly.
        from opal_look_yolo import service_control as sc

        env_extra = {}
        if port is not None:
            env_extra["OPAL_YOLO_PORT"] = str(port)
        if host is not None:
            env_extra["OPAL_YOLO_HOST"] = host
        if data_dir is not None:
            env_extra["OPAL_YOLO_DATA_DIR"] = data_dir
        managed = sc.read_pid()
        if managed is not None and sc.pid_alive(managed):
            sc.kill_pid(managed)
            typer.echo(f"killed running server (pid {managed})")
        sc.pid_path().unlink(missing_ok=True)
        pid = sc.spawn_server(append=append, wait_pid=managed,
                              env_extra=env_extra or None)
        typer.echo(f"started opal-look-yolo (pid {pid}); output -> {sc.log_path()}")

    @service_app_typer.command("stop")
    def service_stop(ctx: typer.Context) -> None:
        """Stop the managed server; not an error when none is running."""
        resp = _rest_or_fallback(ctx, "POST", "/api/v1/service/stop")
        if resp is not None:
            _emit(resp)
            return
        from opal_look_yolo import service_control as sc

        pid = sc.read_pid()
        if pid is None or not sc.pid_alive(pid):
            sc.pid_path().unlink(missing_ok=True)
            typer.echo("no server running")
            return
        sc.kill_pid(pid)
        sc.pid_path().unlink(missing_ok=True)
        typer.echo(f"stopped opal-look-yolo (pid {pid})")

    @service_app_typer.command("log")
    def service_log(
        ctx: typer.Context,
        lines: int = typer.Option(10, "--lines", min=1, max=1000),
    ) -> None:
        """Tail the service log (default 10 lines)."""
        resp = _rest_or_fallback(ctx, "GET",
                                 f"/api/v1/service/log?lines={lines}")
        if resp is not None:
            for line in resp.get("lines", []):
                typer.echo(line)
            return
        from opal_look_yolo import service_control as sc

        tail = sc.tail_log(lines)
        if tail is None:
            _fail({"error": {"code": "not_found",
                             "message": f"no log file at {sc.log_path()}"}})
        for line in tail:
            typer.echo(line)

    app.add_typer(info_app, name="info")
    app.add_typer(engines_app, name="engines")
    app.add_typer(models_app, name="models")
    app.add_typer(hardware_app, name="hardware")
    app.add_typer(predict_app, name="predict")
    app.add_typer(config_app, name="config")
    app.add_typer(profile_app, name="profile")
    app.add_typer(persona_app, name="persona")
    app.add_typer(service_app_typer, name="service")
    register_tree_commands(app, label)
    return app


app = create_cli_app()
yolo_look_app = create_cli_app(label="yolo-look")


def main() -> None:
    app()


def main_yolo_look() -> None:
    yolo_look_app()
