# Research Notes

## Kombu Transport Findings

Kombu exposes transports through a common transport interface and has a virtual
transport base for non-AMQP backends. The virtual base is the right fit for
Solace because it lets Kombu emulate AMQP exchanges and bindings while the
backend implements queue operations.

The v1 transport should use Kombu-owned routing for correctness. Native Solace
topic subscriptions on queues are attractive for performance, but AMQP topic
semantics and Solace SMF wildcard semantics are not identical. The implementation
can add native routing later as an opt-in mode after the baseline behavior is
stable.

Important Kombu virtual `Channel` methods:

- `_get(queue, timeout=None)`: return the next raw Kombu message or raise
  `queue.Empty`
- `_put(queue, message)`: place a Kombu message onto a queue
- `_purge(queue)`: remove ready messages and return a count where possible
- `_size(queue)`: return queue depth if available
- `_delete(queue, ...)`: delete or purge queue resources
- `_new_queue(queue, **kwargs)`: create or ensure queue existence
- `_has_queue(queue, **kwargs)`: passive queue declaration support

The virtual base handles:

- `basic_publish`
- `basic_get`
- `basic_consume`
- `basic_ack`
- `basic_reject`
- `basic_qos`
- direct/topic exchange lookup
- routing table state
- body encoding
- delivery tag generation
- QoS tracking

One Kombu virtual behavior must be overridden: unacknowledged restore on close.
Solace persistent messages remain on the broker until acknowledged, so the
transport must not republish unacknowledged messages during channel shutdown.

Representative Kombu tests:

- `t/unit/transport/virtual/test_base.py`
- `t/unit/transport/test_redis.py`
- `kombu/transport/SQS/__init__.py` as a cloud-backed virtual transport example
- `kombu/transport/mongodb.py` as a simpler virtual transport with persistent
  storage and fanout support

## Solace Python API Findings

The Solace Python API uses a builder model starting from
`MessagingService.builder()`. The messaging service creates publisher builders,
receiver builders, and outbound message builders.

Solace Python API 1.11 documentation says it supports:

- publish/subscribe
- request/reply
- persistent message publishing
- persistent message receiving
- queue provisioning through persistent receiver builders
- client acknowledgement for persistent receivers
- authentication strategies including basic username/password, Kerberos,
  client certificate, and OAuth2
- TLS transport security strategies

For Celery/Kombu, persistent messaging is the baseline because direct messages
are at-most-once and not retained for offline consumers. Solace persistent
messages are documented for guaranteed, at-least-once delivery and are routed
to queues through topic-to-queue mapping.

Solace persistent publishing is topic-based. The v1 transport should publish to
internal per-queue topics and ensure each Solace queue subscribes to its own
internal topic. This keeps Solace as the durable store while Kombu remains the
only routing authority.

Important Solace concepts for this transport:

- `MessagingService`: connection and factory for builders
- `PersistentMessagePublisher`: persistent publish path
- `PersistentMessageReceiver`: queue receive path with ack support
- `OutboundMessageBuilder`: outbound payload and metadata
- `Queue`: queue resource for persistent receivers
- `Topic` and `TopicSubscription`: destination/subscription resources
- `MissingResourcesCreationStrategy`: controls queue creation on receiver start
- `BasicUserNamePassword`: basic authentication strategy
- `TLS`: transport security strategy

Detailed source notes and implementation constraints are saved in
[SOURCE_NOTES.md](SOURCE_NOTES.md).

## Compatibility Notes

Solace documents that `solace-pubsubplus` cannot be used with Python
multiprocessing. Celery commonly uses prefork multiprocessing by default. This
does not automatically make the transport impossible, but it means the first
supported Celery worker mode should be conservative, likely `solo`, until a
process-local connection lifecycle is proven.

Kombu transport capability flags should initially be conservative:

- `asynchronous=False`
- `exchange_type=frozenset(["direct", "topic"])`
- `heartbeats=False`

The transport can expand these only after tests and broker behavior prove them.

## Source Links

- Kombu repository: <https://github.com/celery/kombu>
- Kombu virtual transport docs: <https://docs.celeryq.dev/projects/kombu/en/latest/reference/kombu.transport.virtual.html>
- Kombu virtual base source: <https://github.com/celery/kombu/blob/main/kombu/transport/virtual/base.py>
- Kombu virtual base tests: <https://github.com/celery/kombu/blob/main/t/unit/transport/virtual/test_base.py>
- Kombu SQS transport source: <https://github.com/celery/kombu/blob/main/kombu/transport/SQS/__init__.py>
- Kombu MongoDB transport source: <https://github.com/celery/kombu/blob/main/kombu/transport/mongodb.py>
- Solace Python API overview: <https://docs.solace.com/API/Messaging-APIs/Python-API/python-home.htm>
- Solace Python API reference: <https://docs.solace.com/API-Developer-Online-Ref-Documentation/python/>
- Solace messaging package reference: <https://docs.solace.com/API-Developer-Online-Ref-Documentation/python/source/rst/solace.messaging.html>
- Solace queue creation guide: <https://docs.solace.com/API/API-Developer-Guide-Python/Python-API-Create-Queues.htm>
- Solace persistent publish guide: <https://docs.solace.com/API/API-Developer-Guide-Python/Python-PM-Publish.htm>
