# OPAL Look YOLO CLI

`opal-yolo` is the command-line client for the OPAL Look YOLO adapter. It can
also be invoked as `yolo-look`; both executable names expose the same Typer
application. Commands use the REST contract's paths, schemas, and
error semantics. By default, each command creates the FastAPI application in the
CLI process and sends the request through `httpx.ASGITransport`; no TCP listener
or separate service process is required. Supplying `--url` or
`OPAL_YOLO_URL` explicitly switches the same commands to a remote REST service.

Use the CLI to inspect service health, discover engines and hardware, manage
model lifecycle, run synchronous image predictions, submit frame envelopes, and
inspect the complete command tree.

## Installation

Install the package and its CLI entry point:

```bash
python -m pip install -e .
```

Ultralytics is a required project dependency and is used by the embedded
application or a remote service for real inference. The adapter still degrades
safely if the package cannot be imported in a development environment.

Verify the entry point:

```bash
opal-yolo --help
opal-yolo tree
# Equivalent alias:
yolo-look tree
```

## Global configuration

Global options must appear before the command group or command:

```bash
opal-yolo info health
opal-yolo --url http://127.0.0.1:8086 --token "$TOKEN" info health
```

| Option | Environment variable | Default | Purpose |
|---|---|---|---|
| `--url` | `OPAL_YOLO_URL` | embedded ASGI | Remote adapter base URL; omit for in-process execution |
| `--token` | `OPAL_YOLO_TOKEN` | unset | Bearer token sent as `Authorization: Bearer ...` |
| `--install-completion` | — | — | Install shell completion |
| `--show-completion` | — | — | Print shell completion script |

Command-line options take precedence over environment variables. If the service
is in loopback development mode with authentication disabled, omit `--token`.

The CLI sends REST-shaped requests to `/api/v1/...` either over ASGI or over
HTTP when `--url` is supplied. It never places the bearer token in a query
string or request payload.

## Execution modes

### Embedded ASGI mode — default

Omit `--url` and `OPAL_YOLO_URL`:

```bash
opal-yolo info health
```

The command creates the same FastAPI application used by `uvicorn`, but the
request is dispatched directly through ASGI. Service settings still come from
`OPAL_YOLO_*` environment variables and `.env`, including model directories,
authentication policy, image limits, and remote-source policy.

Because the application is created inside each CLI invocation, runtime model
state does not persist between separate commands. `predict` automatically loads
the requested model for that invocation, so use direct predictions for the
normal embedded workflow. Use remote mode when you need a long-lived loaded
model across separate CLI calls.

### Remote REST mode

Provide `--url` or set `OPAL_YOLO_URL`:

```bash
opal-yolo --url http://127.0.0.1:8086 info health
```

This is useful for interacting with a long-lived shared adapter process.

## Output and exit behavior

Successful commands print formatted JSON to standard output.

```json
{
  "engine_id": "yolo",
  "available": true,
  "tasks": [
    "detect"
  ]
}
```

API and transport failures also print a JSON object to standard output and exit
with status `1`. The service's `OpalError` envelope is preserved when present:

```json
{
  "error": {
    "code": "not_found",
    "message": "Model not found",
    "details": {
      "model_id": "missing"
    }
  }
}
```

Connection failures use a local error envelope:

```json
{
  "error": {
    "code": "connection_failed",
    "message": "..."
  }
}
```

Typer usage errors, such as a missing required option or an invalid
`--confidence` range, are reported by the command parser and normally use exit
status `2`.

## Command tree

```text
opal-yolo [--url] [--token]
├── predict source --model-id [--confidence] [--device] [--engine-options]
│   [--include-native]
│   └── frame --image --frame --model-id [--confidence] [--device]
│       [--engine-options] [--include-native]
├── tree [--ascii]
├── info
│   └── health
├── engines
│   ├── list
│   ├── discover
│   ├── show [engine_id]
│   └── capabilities [engine_id]
├── models
│   ├── list
│   ├── show model_id
│   ├── load model_id [--device]
│   └── unload model_id
├── hardware
│   ├── list
│   └── show device_id
├── config
│   ├── setting  list · show · set · remove
│   ├── save [--out]
│   ├── load [--in]
│   └── validate [--in]
├── profile
│   ├── list · show · add · update · remove · activate
├── persona
│   ├── list · add · show · update · remove · validate
└── service
    ├── start [--append] [--host] [--port] [--data-dir]
    ├── stop
    └── log [--lines]
```

`predict` is both a command and a group: `predict SOURCE ...` submits a JSON
prediction and `predict frame ...` submits a multipart frame (the old
`predict-frame` spelling is retired).

The `tree` output is generated from the live Typer/Click application, so it
reflects the installed CLI rather than a hand-maintained command list.
Required arguments and options are unbracketed; optional parameters are shown
in brackets. `tree` is a local introspection command and does not instantiate
the embedded FastAPI application or contact a remote service.

## Command reference

### `info`

Service metadata and readiness.

```bash
opal-yolo info health
```

- `health` calls `GET /api/v1/health/` and returns the kernel
  `OpalHealthReport` (service name/version plus `details.engine_available`).
  The retired `info show`/`GET /api/v1/info/` surface is gone in v0.1.0.

### `engines`

Engine catalog, discovery, details, and advertised capability schema.

```bash
opal-yolo engines list
opal-yolo engines discover
opal-yolo engines show [engine_id]
opal-yolo engines capabilities [engine_id]
```

`engine_id` defaults to `yolo`. Capabilities include the JSON Schema used by
the service to validate `engine_options`.

### `hardware`

Local compute-device catalog.

```bash
opal-yolo hardware list
opal-yolo hardware show DEVICE_ID
```

Typical device IDs include `cpu`, `cuda:0`, or another engine-local identifier
reported by `hardware list`.

### `models`

Local model catalog and lifecycle operations.

```bash
opal-yolo models list
opal-yolo models show MODEL_ID
opal-yolo models load MODEL_ID [--device DEVICE_ID]
opal-yolo models unload MODEL_ID
```

- `load` sends `{}` by default and `{"device": "..."}` when `--device` is supplied.
- Loading is repeat-safe within one application runtime.
- In embedded mode, each command receives a new runtime, so `load` and `unload`
  report state for that invocation only; `predict` performs its own automatic
  model load.
- `unload` does not delete model files.
- Unloading while predictions are active can return `409 conflict`.

### `predict`

Run a synchronous prediction against a service-accessible image source.

```bash
opal-yolo predict SOURCE \
  --model-id MODEL_ID \
  [--confidence 0.25] \
  [--device DEVICE_ID] \
  [--engine-options JSON] \
  [--include-native]
```

`SOURCE` is passed through to the service. Local filesystem paths and `file://`
URIs work by default. HTTP(S) sources are available only when the service is
configured with `OPAL_YOLO_ALLOW_REMOTE_SOURCES=true` and the remote host is in
`OPAL_YOLO_ALLOWED_REMOTE_HOSTS`.

`--confidence` must be between `0.0` and `1.0`, inclusive.

`--engine-options` must be a JSON object encoded as one command-line argument.
Allowed names and value constraints are defined by `engines capabilities`.

`--include-native` asks the engine to return sanitized engine-native output in
addition to normalized detections.

### `predict frame`

Submit one JPEG or PNG frame plus a frame metadata envelope.

```bash
opal-yolo predict frame \
  --image frame.png \
  --model-id MODEL_ID \
  --frame FRAME_JSON \
  [--confidence 0.25] \
  [--device DEVICE_ID] \
  [--engine-options JSON] \
  [--include-native]
```

`--image` must point to a readable local file. The CLI sends `image/png` for a
`.png` suffix and `image/jpeg` for other suffixes.

`--frame` must be a JSON object matching the contract's `FrameEnvelope`:

```json
{
  "stream_id": "camera-1",
  "frame_id": "00042",
  "sequence": 42,
  "captured_at": "2025-01-01T12:00:00Z",
  "image": {
    "width": 640,
    "height": 480
  },
  "transaction_id": "optional-correlation-id",
  "request_id": "optional-request-id",
  "causation_id": "optional-causation-id"
}
```

Additional envelope properties are allowed and are echoed by the service. The
`image.width` and `image.height` values must match the decoded uploaded image.
The service does not acquire RTSP frames; OPAL Look or another caller supplies
each frame explicitly.

## JSON quoting

JSON strings require shell-appropriate quoting.

POSIX shell:

```bash
opal-yolo predict image.png --model-id yolov8n \
  --engine-options '{"imgsz": 640, "half": false}'
```

PowerShell:

```powershell
opal-yolo predict image.png --model-id yolov8n `
  --engine-options '{\"imgsz\": 640, \"half\": false}'
```

For complex frame envelopes, storing the JSON in a file and reading it into a
shell variable can be easier to maintain. The current CLI expects the frame
envelope itself as a string; it does not accept a JSON file path for `--frame`.

## Authentication behavior

When adapter authentication is enabled, provide a token globally or through the
environment. This applies to both embedded ASGI mode and remote REST mode:

```bash
opal-yolo --token "$TOKEN" models list
opal-yolo --url https://yolo.example --token "$TOKEN" models list
# or
export OPAL_YOLO_TOKEN="$TOKEN"
opal-yolo models list
```

Missing or invalid credentials produce the adapter's `unauthorized` error
envelope and exit status `1`. When the embedded application is configured for
loopback development without authentication, omit the token.

## COOKBOOK

### Recipe 1 — Show adapter metadata

```bash
opal-yolo info health
```

Expected output contains `name`, `version`, and `engine_id`.

### Recipe 2 — Check health before submitting work

```bash
opal-yolo info health
```

Use this in scripts before loading a model or predicting. A `503` response is
reported as JSON with a nonzero exit code.

### Recipe 3 — Configure a reusable remote endpoint and token

```bash
export OPAL_YOLO_URL=http://127.0.0.1:8086
export OPAL_YOLO_TOKEN='local-token'
opal-yolo info health
```

PowerShell equivalent:

```powershell
$env:OPAL_YOLO_URL = 'http://127.0.0.1:8086'
$env:OPAL_YOLO_TOKEN = 'local-token'
opal-yolo info health
```

### Recipe 4 — Print the complete CLI tree

```bash
opal-yolo tree
```

Use this to discover commands and required parameters on the installed version.

### Recipe 5 — Print a log-safe ASCII CLI tree

```bash
opal-yolo tree --ascii
```

This avoids Unicode box-drawing characters and terminal styling.

### Recipe 6 — List known engines

```bash
opal-yolo engines list
```

The response is an array of `Engine` objects with availability, tasks, version,
and optional capability metadata.

### Recipe 7 — Refresh engine availability

```bash
opal-yolo engines discover
```

Discovery refreshes installed-engine availability without installing software,
downloading weights, or changing persistent configuration.

### Recipe 8 — Inspect the YOLO engine

```bash
opal-yolo engines show yolo
```

The `yolo` argument may be omitted because it is the default.

### Recipe 9 — Read valid engine options

```bash
opal-yolo engines capabilities yolo
```

Use `options_schema` to determine which `--engine-options` properties are
valid for the current engine.

### Recipe 10 — List compute devices

```bash
opal-yolo hardware list
```

Record a suitable `device_id` before selecting a device explicitly.

### Recipe 11 — Inspect a compute device

```bash
opal-yolo hardware show cpu
```

Replace `cpu` with an ID returned by `hardware list`, such as `cuda:0` when a
CUDA device is detected.

### Recipe 12 — List local model registrations

```bash
opal-yolo models list
```

Use the `model_id` value in subsequent `show`, `load`, `unload`, `predict`, and
`predict frame` commands.

### Recipe 13 — Inspect one model

```bash
opal-yolo models show yolov8n
```

The response includes tasks, loaded state, availability, and metadata such as
file format or size.

### Recipe 14 — Load a model on the default device

```bash
opal-yolo models load yolov8n
```

The adapter selects an appropriate device. Repeated load calls are safe and
return current state. In embedded mode, the loaded state applies only to this
CLI invocation.

### Recipe 15 — Load a model on a selected device

```bash
opal-yolo models load yolov8n --device cuda:0
```

Use `hardware list` first to verify the device exists and is available.

### Recipe 16 — Unload an idle model

```bash
opal-yolo models unload yolov8n
```

Unloading removes the runtime model handle but does not delete the model file.
A `409` response means the model is currently in use. In embedded mode, use
this to exercise lifecycle behavior in the invocation; it is not persistent
after the command exits.

### Recipe 17 — Run a basic local-image prediction

```bash
opal-yolo predict ./images/street.jpg --model-id yolov8n
```

The service resolves the path on the service host, decodes the image, and
returns normalized detections.

### Recipe 18 — Predict from a file URI

```bash
opal-yolo predict file:///C:/data/street.jpg --model-id yolov8n
```

Use forward slashes in a `file://` URI, including on Windows. Local `file://`
sources do not require remote-source allowlisting.

### Recipe 19 — Tune confidence, device, and engine options

```bash
opal-yolo predict ./images/street.jpg \
  --model-id yolov8n \
  --confidence 0.35 \
  --device cuda:0 \
  --engine-options '{"imgsz": 640}'
```

Unknown or invalid option names are rejected by the service according to the
advertised capability schema.

### Recipe 20 — Submit one frame envelope for prediction

```bash
opal-yolo predict frame \
  --image ./frames/00042.png \
  --model-id yolov8n \
  --confidence 0.3 \
  --frame '{
    "stream_id": "camera-1",
    "frame_id": "00042",
    "sequence": 42,
    "captured_at": "2025-01-01T12:00:00Z",
    "image": {"width": 640, "height": 480},
    "transaction_id": "txn-123",
    "request_id": "req-456",
    "causation_id": "cause-789"
  }'
```

The response echoes the supplied frame envelope and contains normalized
detections aligned to the original image coordinates.

## Scripting notes

### Wait for a healthy remote service

```bash
until opal-yolo --url http://127.0.0.1:8086 info health >/dev/null; do
  sleep 1
done
opal-yolo --url http://127.0.0.1:8086 models list
```

### Feed JSON output to `jq`

```bash
MODEL_ID=$(opal-yolo models list | jq -r '.[0].model_id')
opal-yolo models load "$MODEL_ID"
opal-yolo predict ./image.png --model-id "$MODEL_ID" |
  jq '.detections[] | {class_name, confidence, box}'
```

### Preserve API errors for diagnostics

```bash
if ! opal-yolo models unload "$MODEL_ID" >result.json; then
  cat result.json
  exit 1
fi
```

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `connection_failed` | Wrong remote URL or service not running | Verify `--url`; omit it for embedded ASGI mode |
| `configuration_failed` | Invalid embedded `OPAL_YOLO_*` settings | Inspect the reported setting and retry |
| `unauthorized` | Missing/wrong bearer token | Set `--token` or `OPAL_YOLO_TOKEN` |
| `not_found` model | Model not discovered under configured roots | Run `models list`; check service `OPAL_YOLO_MODEL_DIRS` |
| `validation_failed` device | Device ID unavailable or unknown | Run `hardware list`; use a listed available ID |
| `validation_failed` options | Unsupported `engine_options` | Run `engines capabilities` and use its schema |
| `payload_too_large` | Image exceeds service limit | Reduce image size or raise service `max_image_bytes` |
| `capacity_exceeded` | Bounded inference capacity is exhausted | Retry later or raise service `max_concurrent_predictions` |
| `service_unavailable` | Ultralytics/model/runtime unavailable | Reinstall dependencies and verify model/runtime logs |
| `Remote image sources are not permitted` | HTTP(S) source is not allowlisted | Use a local/file source or configure the allowlist |
