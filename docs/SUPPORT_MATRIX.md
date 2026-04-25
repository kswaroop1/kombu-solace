# Support Matrix

## Current Support Level

This project is a working transport implementation with unit, broker, and
Celery solo-worker smoke coverage. It is not yet a production release because
long soak, repeated performance benchmarks, and broader Celery pool validation
are still required.

## Supported Baseline

- Python: 3.10 or newer.
- Kombu: 5.3 or newer.
- Celery: 5.3 or newer; tested locally with Celery 5.6.3.
- Solace Python API: `solace-pubsubplus` 1.11 or newer.
- Solace broker: PubSub+ broker with persistent messaging and required message
  outcome support for `FAILED` and `REJECTED`.
- Celery worker pool: `solo` for the first supported Celery target.

## Not Claimed Yet

- Celery prefork support.
- Celery multiprocessing support.
- Thread, gevent, or eventlet worker pools.
- Native Solace routing mode.
- Fanout exchange support.
- Broker-side TTL, priority, dead-message-queue policy management, or
  exchange-to-exchange bindings.

## Worker Pool Decision

`solace-pubsubplus` documents that the Python API cannot be used with Python
`multiprocessing`. Celery prefork uses multiprocessing, so prefork must remain
unsupported until a worker-process-local connection lifecycle is implemented
and proven. The supported Celery target is currently `pool="solo"`.

## Defaults

- `routing_mode="kombu"` remains the v1 default and only implemented mode.
- `publish_confirm_mode="async"` remains the default for throughput.
- `publisher_buffer_capacity=1000` is the default async publish/back-pressure
  capacity.
- `publisher_back_pressure_strategy="wait"` is the default to keep memory
  bounded.
- `create_missing_queues=True` remains the development-friendly default.
  Production deployments should pre-provision queues and set
  `create_missing_queues=False` where broker governance requires it.
- Native Solace routing is a v2 opt-in feature only after separate wildcard,
  direct/topic, and duplicate-delivery tests are complete.

## Celery Test Notes

The in-process Celery testing worker and producer share one Python process.
Tests set `broker_pool_limit=0` so producer connections do not reuse or disturb
the worker consumer connection. This setting is part of the test harness, not a
general production requirement.
