# Architecture

## Design Summary

The transport will be a Kombu virtual transport backed by Solace persistent
messaging. Kombu owns AMQP-compatible exchange, binding, and routing semantics
in the first implementation. Solace owns durable storage, delivery,
acknowledgement, broker back-pressure, and network IO.

```text
Kombu Producer/Consumer
        |
        v
kombu_solace.transport.Transport
        |
        v
kombu_solace.transport.Channel
        |
        v
kombu_solace.adapter.SolaceMessagingAdapter
        |
        v
solace-pubsubplus MessagingService / publisher / receiver / queue resources
```

The design favors correctness first. Solace-native broker routing can be added
later as an opt-in optimization after the Kombu behavior suite proves the
baseline.

## Core Decisions

- Default routing mode: `kombu`.
- Default delivery mode: Solace persistent messages.
- Default queue type for Celery task queues: durable, non-exclusive Solace
  queue.
- Default publish mode: asynchronous persistent publish with bounded
  back-pressure and receipt tracking.
- Destination root: configurable by `topic_prefix`, `application`,
  `environment`, and `namespace`, so one Solace VPN can host multiple isolated
  non-production environments and applications.
- Physical Solace queue resource names are mapped separately from Kombu logical
  queue names, allowing corporate conventions such as
  `corp.orders.DEV1.celery` without changing Celery routing config.
- Strict publish mode: optional synchronous publish awaiting broker
  acknowledgement.
- Unacked restore: disabled at the Kombu virtual layer; Solace broker redelivery
  is the source of truth.
- Negative acknowledgement: `requeue=True` maps to Solace `Outcome.FAILED`;
  `requeue=False` maps to `Outcome.REJECTED`.
- Durable queue deprovisioning: not available through the Solace Python
  messaging API; queue delete/size/purge require explicit support paths.

## Kombu Boundary

The transport should reuse Kombu virtual behavior for:

- exchange declaration equivalence checks
- direct and topic exchange routing tables
- queue binding state
- payload body encoding and decoding
- delivery tag generation
- QoS prefetch checks
- consumer callback registration

The core Kombu methods to implement or override are:

- `Transport.establish_connection`
- `Transport.close_connection`
- `Channel._new_queue`
- `Channel._has_queue`
- `Channel._put`
- `Channel._get`
- `Channel._purge`
- `Channel._size`
- `Channel._delete`
- `Channel.basic_ack`
- `Channel.basic_reject`
- `Channel.basic_recover`
- `Channel.close`

The channel must set `do_restore = False`. Kombu's virtual restore republishes
unacknowledged messages on close. That is wrong for Solace persistent delivery
because unacknowledged messages remain on the broker and can be redelivered when
the receiver disconnects or reconnects. Republish-on-close can duplicate tasks.

## Adapter Boundary

Solace imports must stay behind adapter classes. Kombu-facing tests should be
able to use fakes without importing or installing Solace network clients.

### Messaging Adapter

The messaging adapter wraps `solace-pubsubplus` messaging APIs only:

- `connect(settings) -> None`
- `close() -> None`
- `ensure_queue(queue_spec) -> None`
- `ensure_queue_subscription(queue_name, topic) -> None`
- `publish(topic, payload, headers, properties, confirm_policy) -> PublishResult`
- `receive(queue_name, timeout_ms) -> SolaceInbound | None`
- `ack(delivery_ref) -> None`
- `settle_failed(delivery_ref) -> None`
- `settle_rejected(delivery_ref) -> None`
- `close_receiver(queue_name) -> None`
- `flush_publisher(timeout_ms) -> None`

The adapter owns:

- `MessagingService`
- persistent publisher creation and start
- persistent receiver creation and start
- publish receipt listener state
- receiver acknowledgement and settlement calls
- Solace exception normalization into transport-level errors

### Optional Management Adapter

Management operations must be separated from the messaging adapter because the
Solace Python messaging API cannot deprovision durable queues created through
missing resource creation.

The optional management adapter may use SEMP, broker CLI automation, or a future
Solace API if one becomes available:

- `delete_queue(name) -> None`
- `queue_size(name) -> int | None`
- `purge_queue(name) -> int | None`
- `remove_queue_subscription(queue_name, topic) -> None`

Without a management adapter:

- `_delete` should terminate local receivers and clean local state but must not
  claim that a durable broker queue was removed.
- `_size` should return `0` or a documented unavailable value according to Kombu
  expectations.
- `_purge` can use queue browsing and `remove()` only if explicitly enabled and
  documented as best effort when active consumers exist.

## Routing Model

### V1: Kombu-Owned Routing

The first implementation uses Kombu's virtual exchange routing. That means:

- `basic_publish` can keep the Kombu virtual flow.
- Kombu resolves exchange/routing-key bindings to one or more queues.
- `Channel._put(queue, message)` publishes to a Solace internal topic for that
  exact queue.
- Each Solace queue receives exactly one internal topic subscription for its own
  queue ingress topic.
- `queue_bind` updates Kombu virtual state only. It must not create
  exchange/routing-key subscriptions on Solace queues in this mode.

This avoids duplicate delivery and preserves Kombu's topic exchange semantics
exactly. Kombu's virtual topic exchange documents `#` as one or more words and
implements matching through its own regex table; Solace-native wildcard routing
must not replace that behavior until separately tested.

The tradeoff is that publishing to N matched queues becomes N Solace persistent
publishes. This is acceptable for the first reliable transport because common
Celery task routing usually targets one queue. Performance tests will measure
this explicitly before any production claim.

### Internal Topic Naming

The internal queue ingress topic should be deterministic and isolated from user
topics:

Default:

```text
_kombu/{environment}/{namespace}/queue/{encoded_queue_name}
```

With `topic_prefix="corp/nonprod"` and `application="orders"`:

```text
corp/nonprod/orders/{environment}/_kombu/{namespace}/queue/{encoded_queue_name}
```

Requirements:

- keep normal organization, application, environment, and namespace values
  readable when they are safe topic levels
- encode unsafe topic root segments and queue names so `/`, `*`, `>`, NULL, and
  non-ASCII edge cases cannot change Solace topic structure or wildcard scope
- keep the final topic within Solace limits, including 250 bytes and 128 levels
- provide a collision-resistant fallback for very long queue names
- test round trips for normal Celery queue names, punctuation, slashes, unicode,
  and long names

### Physical Queue Naming

Kombu and Celery continue to use logical queue names such as `celery`,
`priority.high`, or `worker.broadcast`. The Solace adapter boundary maps those
logical names to physical broker queue resources.

Default behavior is intentionally unchanged:

```text
logical queue: celery
physical queue: celery
```

When `queue_name_prefix` or `application` is set, the default physical naming
convention is:

```text
{queue_name_prefix}.{application}.{environment}.{logical_queue}
```

Empty prefix/application fields are omitted. A custom `queue_name_template` can
override the convention and may use `{prefix}`, `{application}`, `{app}`,
`{environment}`, `{env}`, `{queue}`, or `{logical_queue}`.

This mapping must be used consistently for:

- queue creation
- receiver creation
- queue existence checks
- ack/reject delivery references
- SEMP size and purge operations
- receiver-drain purge fallback

Internal routing topics still include the logical queue name in encoded form,
because Kombu-owned routing publishes once per matched logical queue.

### Future: Native Solace Routing

A later optional `routing_mode="native"` may publish once to a Solace topic and
let Solace queue topic subscriptions route messages. That mode must be designed
and tested separately because:

- AMQP topic `*` and Solace `*` are close enough for one topic word/level.
- Kombu topic `#` is implemented by Kombu's regex matcher and can appear in
  positions Solace `>` cannot represent directly.
- Solace `>` is a one-or-more wildcard at the last topic level.
- Exact direct routing can be optimized natively, but mixed direct/topic/fanout
  behavior needs dedicated translation tests.

Native routing is not part of the v1 correctness baseline.
Any future native routing mode must use conservative wildcard translation:
literal words map to Solace topic levels, `*` maps to `*`, and terminal `#`
can map to `>` only when the pattern is otherwise safe. Unsafe patterns must
fall back to Kombu-owned routing or fail clearly.

## Queue Lifecycle

Queue declaration should map Kombu queue properties to Solace queue resources:

- durable shared queue: `Queue.durable_non_exclusive_queue(name)`
- durable exclusive queue: `Queue.durable_exclusive_queue(name)`
- auto-delete or exclusive temporary queue: `Queue.non_durable_exclusive_queue`
  where that matches Kombu behavior

Durable queue creation uses `MissingResourcesCreationStrategy.CREATE_ON_START`
when `create_missing_queues=True`. The Solace Python API creates durable queues
through persistent receiver start, but it cannot deprovision those durable
queues. The implementation must document that durable cleanup requires SEMP,
CLI, or pre-provisioning.

Queue binding in v1 does not create user routing subscriptions. It only ensures
that the internal queue ingress topic is present on the Solace queue.

## Message Mapping

Kombu virtual messages are dictionaries with:

- `body`
- `headers`
- `properties`
- `content-type`
- `content-encoding`

The v1 transport should serialize the full Kombu message envelope as the Solace
message payload. This preserves Celery compatibility and keeps behavior
testable.

The Solace message should also carry selected native properties when useful for
observability and broker tooling:

- Kombu delivery tag or correlation id as application message id when safe
- content type and encoding as properties
- task name and queue name as user properties when present

The native properties are secondary. The serialized envelope is authoritative.

## Acknowledgement Model

Solace persistent receivers default to client acknowledgement. The transport
must keep that mode for normal Kombu consumers.

Required behavior:

- Store a delivery tag to Solace delivery reference mapping.
- Include the receiver identity in the delivery reference because ack/settle is
  receiver-specific.
- On `basic_ack`, call Solace `ack` first, then mark Kombu QoS as acked.
- On ack failure, keep the delivery in local unacked state and raise a mapped
  transport error.
- On `basic_reject(requeue=True)`, call Solace `settle(..., Outcome.FAILED)`.
- On `basic_reject(requeue=False)`, call Solace `settle(..., Outcome.REJECTED)`.
- Configure receivers with `with_required_message_outcome_support` when NACK
  support is enabled.
- If broker or API NACK support is unavailable, fail fast during receiver start
  or clearly raise on reject according to the chosen option.
- Do not settle the same inbound message more than once.

For `no_ack=True`, the transport still uses a client-ack receiver and ack
immediately after receiving the message. For direct `basic_get`, this happens
before returning the `Message` to the caller. For consumers, this happens before
the Kombu callback receives the message. This matches Kombu's no-ack contract
while keeping one receiver configuration path.

`basic_recover(requeue=True)` should not republish messages. It can terminate
and recreate the receiver or settle failed messages if that behavior is proven
safe. Until then it should raise a documented `NotImplementedError` or mapped
channel error.

## Publish Model

Persistent publishing is topic-based in Solace. In v1 the topic is always the
internal queue ingress topic selected by `_put(queue, message)`.

Publish options:

- `publish_confirm_mode="async"`: publish asynchronously, track publish receipts,
  cap in-flight messages, and surface receipt failures through transport errors.
- `publish_confirm_mode="sync"`: use synchronous publish awaiting broker
  acknowledgement for stricter producer durability.
- `publisher_back_pressure_strategy="wait"`: default for bounded memory.
- `publisher_back_pressure_strategy="reject"`: raise when the buffer is full.
- `publisher_back_pressure_strategy="elastic"`: allowed only by explicit opt-in
  because Solace documents the default as an unbounded internal buffer.

The transport must flush or terminate the publisher on connection close and
must test receipt failure, timeout, and broker rejection paths.

Async publishing keeps an in-process pending receipt count. The publish receipt
listener decrements the count on both success and failure, stores broker
rejections, and wakes any close/flush waiter. `flush_publisher(timeout_ms)` must
raise a mapped publish failure if receipts do not arrive before the configured
timeout.

## Receive Model

The first implementation should use synchronous `receive_message(timeout_ms)`
behind Kombu `drain_events`.

Reasons:

- Kombu already owns the drain loop and prefetch checks.
- Solace asynchronous receive invokes callbacks on Python threads, which adds
  coordination complexity with Kombu QoS.
- Synchronous receive keeps unit tests deterministic.

The adapter should cache one started persistent receiver per active queue and
must close receivers on channel close. Timeouts must convert from Kombu seconds
to Solace milliseconds.

Performance work should measure whether synchronous receive is enough before
adding an asynchronous receiver bridge.

## Connection Options

Expected Kombu URL and `transport_options` inputs:

- `solace://user:password@host:port/vpn`
- `transport_options["vpn_name"]`
- `transport_options["environment"]`
- `transport_options["queue_name_prefix"]`
- `transport_options["namespace"]`
- `transport_options["application"]` or `transport_options["app"]`
- `transport_options["queue_name_template"]`
- `transport_options["topic_prefix"]` or `transport_options["destination_prefix"]`
- `transport_options["create_missing_queues"]`
- `transport_options["publish_confirm_mode"]`
- `transport_options["publish_ack_timeout"]`
- `transport_options["publisher_back_pressure_strategy"]`
- `transport_options["publisher_buffer_capacity"]`
- `transport_options["receive_timeout"]`
- `transport_options["enable_nacks"]`
- `transport_options["management_url"]`
- `transport_options["management_username"]`
- `transport_options["management_password"]`
- `transport_options["size_strategy"]`
- `transport_options["purge_strategy"]`
- TLS options matching Solace transport security strategy

URL parsing must be tested independently from connection creation.

## Performance Requirements

The plan must include benchmark and soak tests before production release:

- single producer publish throughput
- single consumer receive and ack throughput
- publish latency with async receipts
- publish latency with sync acknowledgement
- memory under publisher back-pressure
- memory under slow consumer and Kombu prefetch limits
- multi-queue routing overhead in Kombu routing mode
- reconnect recovery with unacked messages
- publisher close flush time with in-flight messages

Any claim about preserving Solace performance must be backed by these results.

## Known Constraints

- `solace-pubsubplus` documents that it cannot be used with Python
  multiprocessing. Celery prefork support must not be claimed until a
  process-local connection model is proven.
- Solace Python persistent publishing supports async receipts and synchronous
  publish acknowledgement. The default must balance reliability and throughput.
- Solace Python persistent receivers can only consume persistent messages from
  queues, not directly from topics.
- Solace durable queue creation through missing resource creation cannot be
  deprovisioned through the messaging API.
- Solace queue browsing can remove browsed messages, but purge while active
  consumers are present is not guaranteed to see every message first.
