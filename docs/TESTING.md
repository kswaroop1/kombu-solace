# Testing Strategy

## Principle

Tests should describe Kombu-visible behavior first. The first test suite should
not require a Solace broker and should not import real Solace network clients.

Kombu's own tests provide the model:

- virtual base tests validate the common `Transport` and `Channel` contract
- Redis tests use fake clients and mocked network behavior
- SQS tests isolate cloud-specific behavior behind mocked clients

This project should follow the same pattern, with additional reliability and
performance tests because this transport is intended for Celery workloads.

## Test Layers

### Unit: Kombu Contract

These tests instantiate `kombu.Connection(transport=Transport)` and exercise
real Kombu APIs:

- `Exchange.declare`
- `Queue.declare`
- `Queue.bind`
- `Producer.publish`
- `Consumer.consume`
- `Connection.drain_events`
- `Message.ack`
- `Message.reject`
- queue purge/delete where supported

The Solace adapter is replaced with an in-memory fake that records:

- created queues
- internal queue ingress subscriptions
- published envelopes
- received inbound messages
- acked delivery tags
- failed/rejected settlement calls
- publisher receipt success/failure events

Do not mock Kombu behavior we need to prove.

### Unit: Routing

Routing tests must lock down the v1 decision that Kombu owns routing:

- direct exchange routes to exactly the bound queues
- topic exchange uses Kombu AMQP topic semantics
- Kombu topic `#` matching is preserved
- queue binding does not create user exchange/routing-key Solace subscriptions
- every declared queue has exactly one internal queue ingress subscription
- publish to N matched queues performs N internal publishes
- anonymous exchange publishes to the queue named by `routing_key`
- duplicate queue bindings do not create duplicate internal subscriptions

These tests are the guardrail against mixing Kombu virtual routing and
Solace-native routing accidentally.

Wildcard helper tests must reject unsafe AMQP-to-Solace translations so a future
native routing mode cannot silently change Kombu topic behavior.

### Unit: Queue Lifecycle

Queue tests must cover:

- durable non-exclusive queue declaration for normal Celery queues
- durable exclusive queues when requested
- non-durable exclusive queue behavior for temporary/auto-delete queues
- `create_missing_queues=True` applies missing resource creation
- `create_missing_queues=False` fails clearly on missing queue
- passive declaration maps missing queue to Kombu channel error
- durable queue delete without management adapter does not claim broker
  deprovisioning
- optional management adapter handles delete/size/purge when configured
- SEMP-first size falls back to queue browser count when SEMP is unavailable
- SEMP-first purge falls back to receive-and-ack draining when SEMP is
  unavailable
- queue browser and receiver fallback operations are marked best effort when
  active consumers exist

### Unit: Adapter Mapping

These tests mock `solace.messaging` builders and verify that the adapter:

- builds `MessagingService` with host, VPN, authentication, and TLS settings
- creates persistent publishers with the configured back-pressure strategy
- rejects unbounded elastic back-pressure unless explicitly configured
- registers publish receipt listeners in async confirm mode
- uses synchronous publish in sync confirm mode
- creates persistent receivers with client acknowledgement
- configures `Outcome.FAILED` and `Outcome.REJECTED` when NACK support is
  enabled
- provisions queues according to `create_missing_queues`
- converts Solace inbound messages into transport envelopes
- calls the correct ack/settle APIs
- converts Solace receive timeouts into `queue.Empty`
- maps Solace exceptions into Kombu connection/channel errors

### Unit: Acknowledgement and Redelivery

These tests must prove:

- `basic_ack` calls Solace ack before removing Kombu QoS state
- ack failure leaves the message in local unacked state
- `basic_reject(requeue=True)` settles `Outcome.FAILED`
- `basic_reject(requeue=False)` settles `Outcome.REJECTED`
- settlement failure leaves state consistent and raises a mapped error
- close with unacked messages does not republish and does not duplicate
- `do_restore` is disabled for the channel
- `no_ack=True` on `basic_get` and `basic_consume` immediately acknowledges the
  Solace delivery reference without adding the message to Kombu QoS state
- double ack/reject is rejected by Kombu message state
- NACK unavailable at receiver start fails fast or is disabled according to
  transport options

### Unit: Publish Reliability

Publish tests must cover:

- async publish records in-flight messages and handles successful receipts
- failed publish receipt surfaces through the next transport operation
- publisher close flushes in-flight messages or raises timeout
- sync publish waits for broker acknowledgement
- publish acknowledgement timeout maps to a connection/channel error
- message-too-large errors are mapped and do not corrupt state
- back-pressure `wait`, `reject`, and explicit `elastic` policies are applied
- producer publish after connection close fails clearly

### Unit: Error Mapping

Error mapping tests must cover:

- connection establishment failures map to `SolaceConnectionError`
- publish and receive failures map to `SolaceConnectionError`
- queue declaration failures map to `SolaceChannelError`
- mapped errors are exposed through the transport `connection_errors` and
  `channel_errors` tuples so Kombu/Celery retry code can classify them

### Unit: Reliability and Recovery Checklist

Every reliability-sensitive change should keep tests for these behaviors:

- connection failure is classified as a Kombu retryable connection error
- connect, publish, and receive failures are attempted once by the transport and
  then surfaced to Kombu; reconnect/retry cadence belongs to Kombu/Celery
- publish failure, publish receipt failure, and close-time receipt flush failure
  surface as connection-level failures
- close-time failures still close the Solace adapter and Kombu connection state
- receive failures are connection-level failures, while empty receives preserve
  Kombu's empty/timeout behavior
- queue declaration failures are channel-level failures; missing queues are not
  accidentally converted into connection failures
- ack, no-ack auto-ack, reject/requeue, and reject/discard failures restore the
  delivery reference so local state is not silently lost
- `basic_recover` remains unsupported until broker-native recovery semantics are
  explicitly implemented
- channel close with unacked messages never republishes locally; redelivery is
  left to Solace persistent delivery
- SEMP size/purge failures fall back to browser/receiver strategies only for
  configured fallback modes, and fail fast for SEMP-only modes
- browser/receiver fallback works when no management adapter is configured
- broker integration proves real persistent redelivery after unacked channel
  close and reject/requeue where the broker supports required outcomes
- Celery integration proves `acks_late` task redelivery after worker process
  termination

### Unit: Serialization

These tests verify round-tripping Kombu message envelopes:

- binary body
- JSON body
- headers
- content type and encoding
- delivery info
- correlation id and reply-to
- expiration
- priority, even if broker priority is unsupported initially
- Celery task protocol payload examples
- long headers and non-ASCII-safe envelope handling

### Unit: Naming

Naming tests must cover:

- internal topic generation for simple queue names
- queue names containing `/`, `*`, `>`, spaces, punctuation, and unicode
- different `environment` values isolate internal destination roots
- `topic_prefix` plus `application` produce an isolated Solace topic root for
  task, topic-exchange, and broadcast-style traffic
- very long queue names
- collision-resistant fallback behavior
- Solace topic length and level limits
- physical queue name prefix/application/environment mapping
- custom physical queue name templates
- management and purge fallbacks use physical Solace queue names, not Kombu
  logical queue names

### Broker Integration

Broker integration tests are marked `broker_integration` and skipped unless all
required environment variables are present:

- `SOLACE_HOST`
- `SOLACE_VPN`
- `SOLACE_USERNAME`
- `SOLACE_PASSWORD`
- optional TLS settings
- optional SEMP settings for management tests

Broker-backed tests clean up queues with test prefixes through SEMP when
`SOLACE_CLEANUP_QUEUES` is not disabled. The cleanup protects the local broker
from accumulating durable test queues and exhausting endpoint limits.

Broker integration tests:

- connect and close
- declare durable queue
- create or verify internal queue ingress subscription
- publish persistent message
- consume and ack message
- reject/requeue with `Outcome.FAILED` if broker supports NACKs
- reject/discard with `Outcome.REJECTED` if broker supports NACKs
- unacked message redelivers after receiver close/reconnect
- publish receipt failure is surfaced
- SEMP queue size and purge when management settings are present
- queue purge via browser/receiver fallback when enabled

### Celery Smoke

Celery integration tests are marked `celery_integration`. They come after Kombu
behavior is stable, but before a release claim:

- producer publishes a task
- worker consumes with solo pool
- task succeeds and is acked
- task with `acks_late=True` is redelivered after worker shutdown
- task retry path uses reject/requeue behavior where applicable
- task failure with reject/discard is observed
- worker shutdown with unacked messages does not duplicate through republish

Prefork must remain unsupported until a process-local connection lifecycle is
proven against Solace's multiprocessing limitation.

The initial Celery smoke test is gated by `SOLACE_RUN_CELERY=1`. It starts an
in-process solo worker, publishes one task through the Solace broker, and uses a
memory result backend so the test isolates broker transport behavior.
The worker-interruption redelivery test is gated separately by
`SOLACE_RUN_CELERY_INTERRUPT=1` because it starts subprocess Celery workers and
intentionally terminates the first worker during an `acks_late=True` task.

### Performance and Soak

Performance tests should be opt-in and reproducible:

- publish throughput with async receipts
- publish latency with async receipts
- publish latency with sync acknowledgement
- consumer receive/ack throughput
- slow consumer memory with low Kombu prefetch
- publisher memory under back-pressure
- multi-queue routing overhead in Kombu routing mode
- reconnect and redelivery time
- long-running publish/consume soak with no unbounded memory growth

Use fixed message sizes and report environment details. These tests should not
gate normal unit test runs, but they must gate any public performance claim.

The performance smoke tests are gated by `SOLACE_RUN_PERFORMANCE=1` and print
sync publish, async publish plus receipt flush, consume/ack, multi-queue routing,
and bounded back-pressure memory numbers for fixed payloads. They are intended
to catch obvious regressions and establish local baselines; formal release
benchmarks still need repeated runs and recorded broker/client settings.
The longer publish/consume soak is gated by `SOLACE_RUN_SOAK=1` and uses
`SOLACE_SOAK_MESSAGE_COUNT`.

## Test File Plan

```text
tests/unit/test_connection_options.py
tests/unit/test_naming.py
tests/unit/test_channel_lifecycle.py
tests/unit/test_declare_bind.py
tests/unit/test_routing.py
tests/unit/test_publish.py
tests/unit/test_publish_receipts.py
tests/unit/test_consume.py
tests/unit/test_ack_reject.py
tests/unit/test_no_ack.py
tests/unit/test_serialization.py
tests/unit/test_error_mapping.py
tests/unit/test_management_optional.py
tests/integration/test_broker_smoke.py
tests/integration/test_redelivery.py
tests/integration/test_nack.py
tests/performance/test_publish_consume_bench.py
```

## Mocking Rules

- Use real Kombu `Connection`, `Exchange`, `Queue`, `Producer`, and `Consumer`
  objects in transport tests.
- Mock Solace network objects through the adapter boundary.
- Keep fake adapter behavior deterministic and inspectable.
- Test errors with explicit fake exception classes before wiring real Solace
  exception classes.
- Never hide Kombu virtual routing behind a fake; tests must catch accidental
  duplicate delivery.

## Commands

Use `tests/unit` for the normal unit/default validation. Broker, Celery, and
performance suites are separate opt-in categories.

```powershell
python -m pytest tests/unit
$env:SOLACE_RUN_INTEGRATION='1'; python -m pytest -m broker_integration tests/integration
$env:SOLACE_RUN_CELERY='1'; python -m pytest -m celery_integration tests/integration/test_celery_smoke.py
$env:SOLACE_RUN_CELERY_INTERRUPT='1'; python -m pytest tests/integration/test_celery_worker_interrupt.py
$env:SOLACE_RUN_PERFORMANCE='1'; python -m pytest -m performance tests/performance -s
python -m coverage run -m pytest
python -m coverage report
```

## Coverage

Unit-only coverage:

```powershell
python -m coverage run -m pytest tests/unit -q
python -m coverage report
```

Combined unit plus broker/Celery integration coverage:

```powershell
python -m coverage run -m pytest tests/unit -q
$env:SOLACE_RUN_INTEGRATION='1'; python -m coverage run --append -m pytest tests/integration/test_broker_smoke.py -q
$env:SOLACE_RUN_CELERY='1'; python -m coverage run --append -m pytest tests/integration/test_celery_smoke.py -q
$env:SOLACE_RUN_CELERY_INTERRUPT='1'; python -m coverage run --append -m pytest tests/integration/test_celery_worker_interrupt.py -q
python -m coverage report
python -m coverage xml
python -m coverage html
```

Current local unit coverage is 100% statement and branch coverage across
`kombu_solace`:

```text
Name    Stmts   Miss Branch BrPart  Cover   Missing
---------------------------------------------------
TOTAL     771      0    190      0   100%
```

The generated `.coverage`, `coverage.xml`, and `htmlcov/` artifacts are local
outputs and are not committed.
