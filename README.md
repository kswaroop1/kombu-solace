# kombu-solace

`kombu-solace` will provide a Kombu transport backed by Solace PubSub+ using the
official `solace-pubsubplus` Python package.

The immediate goal is not to implement the transport first. The project will
start by documenting the transport model, writing behavior tests against mocks,
and only then implementing the Solace adapter and Kombu transport surface.

## Target

- Kombu transport scheme: `solace://`
- Kombu integration point: a virtual transport implementing Kombu's
  `kombu.transport.virtual.Transport` and `kombu.transport.virtual.Channel`
  contracts.
- Solace client: `solace-pubsubplus`, currently documented as Solace Messaging
  API for Python 1.11.
- Primary delivery mode: Solace persistent messaging, because Celery tasks need
  durable, acknowledged, at-least-once delivery semantics.
- Test posture: behavior tests first, using mocks/fakes for Solace APIs; broker
  integration tests later and opt-in.

## Planned Package Layout

```text
kombu_solace/
  __init__.py
  config.py             # Typed Python transport options
  transport.py          # Kombu Transport and Channel classes
  adapter.py            # Thin wrapper over solace-pubsubplus APIs
  management.py         # Optional SEMP management adapter
  naming.py             # Solace resource and internal topic naming
  wildcards.py          # Conservative AMQP-to-Solace wildcard helpers
  serialization.py      # Kombu payload to Solace message mapping
  errors.py             # Solace/Kombu error normalization
tests/
  unit/
    test_transport_contract.py
    test_channel_lifecycle.py
    test_publish.py
    test_consume_ack_reject.py
    test_routing.py
  integration/
    test_broker_smoke.py
docs/
  ARCHITECTURE.md
  PLAN.md
  RESEARCH.md
  SOURCE_NOTES.md
  TESTING.md
  MEMORY.md
```

## Transport Scope

The first implementation should support:

- direct and topic exchanges through Kombu's virtual routing table
- Kombu-owned routing by default, using per-queue Solace ingress topics to avoid
  duplicate delivery and preserve AMQP topic semantics
- environment-rooted destination names, so one non-production VPN can safely
  host `DEV1`, `DEV2`, `UAT1`, `UAT3`, and similar environments
- optional physical Solace queue naming conventions such as
  `corp.orders.DEV1.celery` while keeping the Kombu/Celery logical queue name
  as `celery`
- optional Solace topic roots such as `corp/nonprod/orders/DEV1/...` so task,
  topic, and broadcast traffic can be isolated by application and environment
- durable queue declaration mapped to Solace queue resources
- publish to queue-backed Solace topics using persistent messages
- synchronous `basic_get`
- consumer delivery through `drain_events`
- `basic_ack` and `basic_reject(requeue=True)`
- `basic_reject(requeue=False)` mapped to Solace rejected settlement where
  supported
- publish receipt tracking and bounded publisher back-pressure
- queue purge, size, and delete only through explicitly documented support paths
- clear unsupported behavior for fanout, priorities, TTL, exchange-to-exchange
  binding, and broker management features not exposed safely by the Python API

The first implementation should not try to support multiprocessing. Solace's
Python package documents that it cannot be used with Python multiprocessing.
The first Celery target is therefore the `solo` worker pool until a
process-local connection model is proven.

## Development Flow

1. Write unit behavior tests using mocked `solace-pubsubplus` collaborators.
2. Build the Solace adapter API to satisfy the tests without importing Kombu
   internals into adapter tests.
3. Implement the Kombu virtual `Channel` and `Transport`.
4. Add optional broker-backed reliability tests guarded by environment
   variables.
5. Add opt-in performance and soak tests before making performance claims.
6. Validate with Celery-level smoke tests only after Kombu behavior is stable.

## Early Usage Shape

The package registers the `solace` transport alias when `kombu_solace` is
imported:

```python
import kombu_solace
from kombu import Connection

conn = Connection("solace://user:password@broker.example.com:55555/vpn")
```

Until packaging and import behavior are finalized, tests may also pass the
transport class directly with `Connection(transport=kombu_solace.transport.Transport)`.

Typical transport options:

```python
broker_transport_options = {
    "vpn_name": "nonprod",
    "environment": "DEV1",
    "namespace": "orders",
    "application": "orders",
    "queue_name_prefix": "corp",
    "topic_prefix": "corp/nonprod",
    "publisher_back_pressure_strategy": "wait",
    "publisher_buffer_capacity": 1000,
    "size_strategy": "semp_then_browser",
    "purge_strategy": "semp_then_receiver",
    "semp_url": "https://broker.example.com:943",
    "semp_username": "admin",
    "semp_password": "...",
}
```

Naming options:

- `environment`: environment identifier, for example `DEV1`, `UAT3`, or `PROD`.
- `namespace`: transport namespace inside the topic root.
- `application` / `app`: application name used in queue and topic roots.
- `queue_name_prefix`: optional organization or platform prefix for physical
  Solace queue names.
- `queue_name_template`: optional Python format string with `{prefix}`,
  `{application}`, `{app}`, `{environment}`, `{env}`, `{queue}`, and
  `{logical_queue}` fields. If omitted, setting `application` or
  `queue_name_prefix` uses `{prefix}.{application}.{environment}.{queue}` with
  empty fields removed.
- `topic_prefix` / `destination_prefix`: optional Solace topic path prefix. With
  `topic_prefix="corp/nonprod"`, `application="orders"`, and
  `environment="DEV1"`, internal queue ingress topics start with
  `corp/nonprod/orders/DEV1/_kombu/...`.

The transport keeps Kombu/Celery logical queue names unchanged for routing and
only maps them at the Solace adapter boundary. This prevents application code
from needing to know corporate broker naming conventions.

## Local Broker Test Environment

On Windows with Podman, some systems reserve ports around `55555`. If
`Test-NetConnection localhost -Port 55555` fails while the container is running,
map host port `55588` to Solace's container SMF port `55555`.

```powershell
podman run -d --name solace `
  -p 8080:8080 `
  -p 55588:55555 `
  -p 5672:5672 `
  -p 8000:8000 `
  -p 8008:8008 `
  -p 9000:9000 `
  -p 2222:2222 `
  --shm-size=2g `
  -e username_admin_globalaccesslevel=admin `
  -e username_admin_password=admin `
  docker.io/solace/solace-pubsub-standard:latest
```

Run broker-gated tests:

```powershell
$env:SOLACE_RUN_INTEGRATION='1'
$env:SOLACE_HOST='localhost'
$env:SOLACE_PORT='55588'
$env:SOLACE_VPN='default'
$env:SOLACE_USERNAME='sampleUser'
$env:SOLACE_PASSWORD='samplePassword'
$env:SOLACE_SEMP_URL='http://localhost:8080'
$env:SOLACE_SEMP_USERNAME='admin'
$env:SOLACE_SEMP_PASSWORD='admin'
$env:SOLACE_SEMP_VERIFY_TLS='false'
python -m pytest tests/integration -q
```

## References

- Kombu source: <https://github.com/celery/kombu>
- Kombu virtual transport API: <https://docs.celeryq.dev/projects/kombu/en/latest/reference/kombu.transport.virtual.html>
- Solace Python API overview: <https://docs.solace.com/API/Messaging-APIs/Python-API/python-home.htm>
- Solace Python API reference: <https://docs.solace.com/API-Developer-Online-Ref-Documentation/python/>
- Solace persistent publish guide: <https://docs.solace.com/API/API-Developer-Guide-Python/Python-PM-Publish.htm>
- Solace queue creation guide: <https://docs.solace.com/API/API-Developer-Guide-Python/Python-API-Create-Queues.htm>
- Source notes captured for implementation: [docs/SOURCE_NOTES.md](docs/SOURCE_NOTES.md)
