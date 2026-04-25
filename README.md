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
  transport.py          # Kombu Transport and Channel classes
  adapter.py            # Thin wrapper over solace-pubsubplus APIs
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

## References

- Kombu source: <https://github.com/celery/kombu>
- Kombu virtual transport API: <https://docs.celeryq.dev/projects/kombu/en/latest/reference/kombu.transport.virtual.html>
- Solace Python API overview: <https://docs.solace.com/API/Messaging-APIs/Python-API/python-home.htm>
- Solace Python API reference: <https://docs.solace.com/API-Developer-Online-Ref-Documentation/python/>
- Solace persistent publish guide: <https://docs.solace.com/API/API-Developer-Guide-Python/Python-PM-Publish.htm>
- Solace queue creation guide: <https://docs.solace.com/API/API-Developer-Guide-Python/Python-API-Create-Queues.htm>
- Source notes captured for implementation: [docs/SOURCE_NOTES.md](docs/SOURCE_NOTES.md)
