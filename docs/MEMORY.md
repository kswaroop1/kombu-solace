# Project Memory

## Current State

- Repository started empty except for `.git`.
- We are planning before implementation.
- The first implementation target is a Kombu virtual transport backed by
  `solace-pubsubplus`.
- Tests must come before implementation and should use mocks/fakes for Solace.

## Important Decisions

- Use persistent Solace messaging as the baseline.
- Use Kombu virtual transport routing for direct and topic exchanges in v1.
- Publish to Solace through internal per-queue ingress topics in v1.
- Do not create user exchange/routing-key Solace subscriptions in default
  routing mode.
- Keep Kombu/Celery logical queue names in Kombu routing state. Map to physical
  Solace queue resource names only at the adapter/management boundary.
- `environment` alone isolates topics, not physical queue names. Setting
  `application`, `queue_name_prefix`, or `queue_name_template` opts into
  physical queue naming such as `corp.orders.DEV1.celery`.
- `topic_prefix` plus `application` can put all internal queue ingress topics
  under a visible root such as `corp/nonprod/orders/DEV1/_kombu/...`.
- Keep Solace imports behind an adapter boundary.
- Serialize the full Kombu message envelope initially for compatibility.
- Disable Kombu virtual unacked restore because Solace broker redelivery is the
  source of truth.
- Map `reject(requeue=True)` to Solace `Outcome.FAILED` and
  `reject(requeue=False)` to `Outcome.REJECTED` when NACK support is enabled.
- Split messaging operations from optional management operations because the
  Solace Python messaging API cannot deprovision durable queues it creates.
- Use bounded publisher back-pressure by default; unbounded elastic buffering
  requires explicit opt-in.
- Start with conservative capability flags and add features only when tested.
- Do not claim multiprocessing/prefork Celery support until proven.

## Follow-Up Questions for the User

- Which Kombu and Celery versions should define compatibility?
- Should missing Solace queues be auto-created by default?
- What internal topic namespace and queue-name encoding should be the default?
- Is fanout required for the first milestone?
- Should publish wait for persistent broker acknowledgement by default?
- Will production use TLS, OAuth/client certificate auth, or username/password?
- Do we need SEMP-backed management for queue delete/size in v1?
- What default publisher in-flight limit and back-pressure buffer size should we
  use for your expected task size and throughput?

## Risk Register

- Celery prefork may conflict with Solace's multiprocessing limitation.
- Solace queue purge and size may need management APIs outside the messaging API.
- Negative acknowledgement/requeue semantics must be verified against the Python
  API before implementation.
- Publisher acknowledgement policy affects throughput and delivery guarantees.
- Topic naming choices can become hard to migrate once users depend on them.
- Native Solace routing can be faster for multi-queue delivery, but it must not
  replace Kombu-owned routing until AMQP topic semantics are fully tested.
