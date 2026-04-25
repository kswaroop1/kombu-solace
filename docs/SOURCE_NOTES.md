# External Source Notes

Verified on 2026-04-25.

This file captures implementation-relevant facts gathered from external Kombu
and Solace references. Use it when implementing the transport so important API
constraints do not have to be rediscovered.

## Kombu Virtual Transport

Sources:

- Kombu virtual transport docs:
  <https://docs.celeryq.dev/projects/kombu/en/latest/reference/kombu.transport.virtual.html>
- Kombu virtual base source:
  <https://github.com/celery/kombu/blob/main/kombu/transport/virtual/base.py>
- Kombu virtual base tests:
  <https://github.com/celery/kombu/blob/main/t/unit/transport/virtual/test_base.py>
- Kombu SQS transport:
  <https://github.com/celery/kombu/blob/main/kombu/transport/SQS/__init__.py>
- Kombu MongoDB transport:
  <https://github.com/celery/kombu/blob/main/kombu/transport/mongodb.py>

Key points:

- `virtual.Channel` routes direct and topic exchanges before calling `_put`.
- `basic_publish` adds Kombu body encoding, delivery info, and delivery tags.
- `basic_consume` registers callbacks and uses QoS to track unacked messages.
- `basic_ack` and `basic_reject` delegate to `QoS` by default.
- `Channel.close()` restores unacknowledged messages through `_restore` when
  `do_restore=True`.
- For Solace persistent messaging, `do_restore` must be `False` or overridden
  because broker redelivery, not republishing, should handle unacked messages.
- Transport-specific tests should use real Kombu `Connection`, `Exchange`,
  `Queue`, `Producer`, and `Consumer` objects and fake only the backend client.

## Solace Persistent Publishing

Sources:

- Publishing persistent messages:
  <https://docs.solace.com/API/API-Developer-Guide-Python/Python-PM-Publish.htm>
- Publishing messages overview:
  <https://docs.solace.com/API/API-Developer-Guide-Python/publishing-messages.htm>
- Solace Python package:
  <https://pypi.org/project/solace-pubsubplus/>

Key points:

- Persistent messages are the correct Solace delivery mode for at-least-once
  task delivery.
- Persistent publishing is topic-based. A persistent message has a topic
  destination and optional payload.
- Persistent messages are delivered to queues that have matching topic
  subscriptions.
- Persistent publishing can be asynchronous with publish receipt listeners or
  synchronous with `publish_await_acknowledgement`.
- Synchronous publish waits until the broker acknowledges that the message was
  received and persisted, or until timeout.
- The Python API supports publisher back-pressure strategies:
  - elastic/unbounded buffer
  - reject at a configured buffer capacity
  - wait/throttle at a configured buffer capacity
- Elastic buffering is not appropriate as the default for a Celery transport
  because it can grow without bound.
- The common maximum persistent message size is 30 MB; oversize messages raise
  a message-too-large error.
- Publish receipts include success/failure information and can carry user
  context for correlation.

## Solace Persistent Receiving and Settlement

Sources:

- Consuming persistent messages:
  <https://docs.solace.com/API/API-Developer-Guide-Python/Python-PM-Receive.htm>
- Receiver API reference:
  <https://docs.solace.com/API-Developer-Online-Ref-Documentation/python/source/rst/solace.messaging.receiver.html>

Key points:

- Solace Python can consume persistent messages from queues, not from topic
  endpoints.
- Persistent messages remain on the broker queue until acknowledged.
- `receive_message(timeout)` blocks until a message, timeout, service
  interruption, or shutdown.
- Solace timeouts are in milliseconds; Kombu uses seconds in its drain APIs.
- Client acknowledgement is the default receiver acknowledgement mode.
- `ack(message)` removes a successfully processed message from the broker queue.
- `settle(message, Outcome.ACCEPTED)` is equivalent to ack.
- `settle(message, Outcome.FAILED)` means the message was not processed and may
  be redelivered according to queue configuration.
- `settle(message, Outcome.REJECTED)` removes the message and can move it to a
  DMQ if configured.
- Negative outcomes require receiver builder configuration with
  `with_required_message_outcome_support`.
- NACK support requires broker support; older brokers can fail receiver start
  when NACK outcomes are required.
- A message must not be settled more than once.
- Solace async receive invokes callbacks on Python threads and is not an
  asyncio coroutine. The first Kombu implementation should use synchronous
  receive behind Kombu `drain_events`.
- If messages are not drained fast enough, the Solace API may buffer internally
  until its high watermark and then apply back-pressure toward the broker.

## Solace Queue Creation and Management

Sources:

- Creating queues:
  <https://docs.solace.com/API/API-Developer-Guide-Python/Python-API-Create-Queues.htm>
- Browsing queues:
  <https://docs.solace.com/API/API-Developer-Guide-Python/Python-API-Browse-Queues.htm>
- Configuring queues:
  <https://docs.solace.com/Configuring-and-Managing/Configuring-Queues.htm>

Key points:

- The Python messaging API can provision queues through
  `PersistentMessageReceiverBuilder`.
- Durable queue creation uses `MissingResourcesCreationStrategy.CREATE_ON_START`.
- Durable queues created through missing resource creation cannot be
  deprovisioned through the Python messaging API. Use SEMP or CLI for deletion.
- Non-durable exclusive queues are deleted after the creating client disconnects;
  unexpected disconnect can leave them briefly available for reconnect.
- Durable shared Celery task queues should use non-exclusive queue resources.
- Queue topic subscriptions can route persistent messages published to matching
  topics into queues.
- Queue browsing can inspect messages without consuming them.
- Queue browser `remove()` can remove browsed messages from the queue.
- Browser-based purge is best effort if active consumers are also bound because
  consumers can receive/ack messages before the browser sees them.
- Queue browser window size can improve browse throughput but uses memory.

## Solace Topic Syntax

Sources:

- Understanding topics:
  <https://docs.solace.com/Get-Started/what-are-topics.htm>
- Solace Message Format topics:
  <https://docs.solace.com/Messaging/SMF-Topics.htm>

Key points:

- Solace topics use `/` separated levels.
- `*` in a subscription matches one topic level.
- `>` in a subscription matches one or more levels and is used at the last
  level.
- Published topic strings treat wildcard characters as literal characters.
- Topics have limits, including 128 levels and 250 bytes excluding the NULL
  terminator.
- AMQP topic `#` means zero or more words and does not map cleanly to Solace
  `>` in every position. This is why v1 uses Kombu-owned routing.

## Solace Multiprocessing Constraint

Source:

- Solace Python package:
  <https://pypi.org/project/solace-pubsubplus/>

Key points:

- The package states that the Solace Messaging API for Python cannot be used in
  applications that use Python `multiprocessing`.
- Celery prefork uses multiprocessing. Do not claim prefork support until a
  process-local connection lifecycle is implemented and tested.
- The first Celery smoke target is the `solo` worker pool.
