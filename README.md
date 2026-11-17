# OPAL Look YOLO

Standalone FastAPI adapter for local Ultralytics YOLO model discovery, loading, local hardware discovery, and synchronous image/frame inference.

The authoritative API contract is `openapi/opal_look_yolo.yaml`. The implementation provides all 14 contract operations, a Typer REST client, and a no-build static SPA at `/app`.

## Requirements

- Python 3.11 through 3.13
- Ultralytics is a required runtime dependency for real YOLO inference

```bash
python -m pip install -e ".[dev]"
```

The API remains testable in environments where Ultralytics is not installed; the engine reports unavailable and model loading/inference fails safely until the dependency and a supported model are installed.

## Configuration

Environment variables use the `OPAL_YOLO_` prefix.

| Setting | Default | Purpose |
|---|---|---|
| `OPAL_YOLO_HOST` | `127.0.0.1` | Advertised/listen host used by configuration policy |
| `OPAL_YOLO_PORT` | `8086` | Service port |
| `OPAL_YOLO_AUTH_DISABLED` | `true` | May be true only for loopback hosts |
| `OPAL_YOLO_AUTH_TOKEN` | unset | Required when authentication is enabled |
| `OPAL_YOLO_MODEL_DIRS` | `models` | Local model directories, path-separated or JSON array |
| `OPAL_YOLO_MAX_IMAGE_BYTES` | `10485760` | Maximum decoded upload/source bytes |
| `OPAL_YOLO_MAX_CONCURRENT_PREDICTIONS` | `2` | Bounded synchronous inference capacity |
| `OPAL_YOLO_ALLOW_REMOTE_SOURCES` | `false` | Enables HTTP(S) image sources |
| `OPAL_YOLO_ALLOWED_REMOTE_HOSTS` | empty | Comma-separated remote-source host allowlist |
| `OPAL_YOLO_REMOTE_SOURCE_TIMEOUT_SECONDS` | `5.0` | Remote-source timeout |

Authentication is enabled by setting `OPAL_YOLO_AUTH_DISABLED=false` and providing `OPAL_YOLO_AUTH_TOKEN`. Non-loopback deployments cannot disable authentication.

Local paths and `file://` image sources are the default. HTTP(S) sources are rejected unless remote sources are explicitly enabled and their host is allowlisted. Redirect-following is disabled and fetched content must be JPEG or PNG.

## Run

```bash
uvicorn opal_look_yolo.main:app --host 127.0.0.1 --port 8086
```

Then open `http://127.0.0.1:8086/app/` for the SPA. `/` redirects to the SPA.

## CLI

The installed `opal-yolo` command, also available as `yolo-look`, uses the
public REST contract. It runs the FastAPI application through in-process ASGI
by default, so no listener is required. See `docs/CLI.md` for the complete
guide.

```bash
opal-yolo info show
opal-yolo engines list
opal-yolo models load MODEL_ID --device cpu
opal-yolo predict image.png --model-id MODEL_ID
opal-yolo predict-frame \
  --image frame.png --model-id MODEL_ID --frame '{"stream_id":"s","frame_id":"f","sequence":1,"captured_at":"2025-01-01T00:00:00Z","image":{"width":640,"height":480}}'
```

Set `--url` or `OPAL_YOLO_URL` to target a separately running REST service.
`OPAL_YOLO_TOKEN` supplies the bearer token when authentication is enabled.

## Architecture

- FastAPI routes validate and expose contract operations.
- Pydantic DTOs implement request, response, and error schemas.
- FastAPI dependency injection wires settings and services.
- Middleware supplies OPAL correlation headers, request logging, and bearer authentication.
- `OpalError` handlers normalize validation, HTTP, and application failures.
- Engine registry/factory and `Protocol` interfaces isolate the Ultralytics adapter.
- Repository/service boundaries isolate filesystem model discovery and loaded-model state.
- Context-managed model usage counts active predictions and prevents unsafe unload.
- A bounded semaphore limits concurrent inference.
- Pillow source decoding and JSON Schema option validation form the prediction pipeline.
- The Typer CLI routes every command through HTTPX, using embedded ASGI by default or remote HTTP when `--url` is supplied.
- The SPA is a package-bundled static client with no JavaScript build step.

## Contract coverage

| Operation | Status |
|---|---|
| `GET /api/v1/info/` | Verified |
| `GET /api/v1/health/` | Verified |
| `GET /api/v1/engine/` | Verified |
| `POST /api/v1/engine/discover` | Verified |
| `GET /api/v1/engine/{engine_id}` | Verified |
| `GET /api/v1/engine/{engine_id}/capabilities` | Verified |
| `GET /api/v1/model/` | Verified |
| `GET /api/v1/model/{model_id}` | Verified |
| `POST /api/v1/model/{model_id}/load` | Verified |
| `POST /api/v1/model/{model_id}/unload` | Verified |
| `GET /api/v1/hardware/` | Verified |
| `GET /api/v1/hardware/{device_id}` | Verified |
| `POST /api/v1/predict` | Verified |
| `POST /api/v1/predict/frame` | Verified |

Cross-cutting behavior verified by tests includes bearer authentication, OPAL correlation headers, `OpalError` responses, model load/unload conflicts, unsupported option rejection, image size limits, bounded prediction capacity, multipart frame validation, remote-source policy, and OpenAPI path/operation coverage.

## Verification

```bash
pytest
ruff check src tests
python - <<'PY'
import yaml
from openapi_spec_validator import validate
with open('openapi/opal_look_yolo.yaml', encoding='utf-8') as source:
    validate(yaml.safe_load(source))
PY
```

At final verification: `81 passed`; Ruff and OpenAPI validation pass.

## Known limitations

- Ultralytics inference is covered with mocked adapter tests; a real model/GPU smoke test requires suitable weights and hardware.
- Model discovery is read-only and filesystem-backed; there is no persistence API or model installation workflow.
- GPU discovery uses optional Torch integration and otherwise reports a CPU fallback.
- The SPA is intentionally minimal and does not provide a multipart frame upload form.
- `openapi/shared/opal_kernel.yaml` is used as a convention reference; the service contract defines its components locally and does not externally `$ref` the shared file.

## Dotenv configuration

See [docs/DOTENV.md](docs/DOTENV.md) for `.env` loading, initialization, precedence, and `--env-file` / `--no-env-file` behavior.
