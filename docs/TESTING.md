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
- `no_ack=True` immediately acknowledges after message conversion
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
- very long queue names
- collision-resistant fallback behavior
- Solace topic length and level limits
- queue name prefix and namespace isolation

### Integration: Solace Broker

Integration tests should be skipped unless all required environment variables
are present:

- `SOLACE_HOST`
- `SOLACE_VPN`
- `SOLACE_USERNAME`
- `SOLACE_PASSWORD`
- optional TLS settings
- optional SEMP settings for management tests

Initial integration tests:

- connect and close
- declare durable queue
- create or verify internal queue ingress subscription
- publish persistent message
- consume and ack message
- reject/requeue with `Outcome.FAILED` if broker supports NACKs
- reject/discard with `Outcome.REJECTED` if broker supports NACKs
- unacked message redelivers after receiver close/reconnect
- publish receipt failure is surfaced
- queue purge via browser when enabled

### Celery Smoke

Celery tests come after Kombu behavior is stable, but before a release claim:

- producer publishes a task
- worker consumes with solo pool
- task succeeds and is acked
- task with `acks_late=True` is redelivered after worker shutdown
- task retry path uses reject/requeue behavior where applicable
- task failure with reject/discard is observed
- worker shutdown with unacked messages does not duplicate through republish

Prefork must remain unsupported until a process-local connection lifecycle is
proven against Solace's multiprocessing limitation.

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

Planned commands once tests exist:

```powershell
python -m pytest
python -m pytest tests/unit
python -m pytest tests/integration --run-solace-integration
python -m pytest tests/performance --run-solace-performance
python -m coverage run -m pytest
python -m coverage report
```
