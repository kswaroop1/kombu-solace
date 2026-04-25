# Plan and Tracker

## Phase 0: Project Framing

- [x] Confirm repository is greenfield.
- [x] Study Kombu virtual transport contract and representative transport tests.
- [x] Study Solace Python API shape and persistent messaging model.
- [x] Write initial README, architecture, research notes, and test strategy.
- [x] Resolve review gaps in routing, restore, reject/requeue, and management
  boundaries.
- [x] Save external source notes for future implementation reference.

## Phase 1: Test Scaffolding

- [x] Add package skeleton without transport behavior.
- [x] Add pytest configuration and coverage settings.
- [x] Add Solace adapter protocol/fake classes for tests.
- [x] Add fake publish receipt and fake inbound delivery models.
- [x] Add behavior tests for connection option parsing.
- [x] Add behavior tests for internal topic naming, environment root, and limits.
- [x] Add behavior tests for physical queue naming with prefix/application/env.
- [x] Add behavior tests for topic root prefixing with application/env isolation.
- [ ] Add behavior tests for queue declaration lifecycle.
- [x] Add behavior tests proving queue bindings do not create user Solace
  subscriptions in default Kombu routing mode.
- [x] Add behavior tests for direct exchange publishing.
- [x] Add behavior tests for topic exchange publishing, including Kombu `#`
  semantics.
- [x] Add conservative wildcard translation tests for future native routing.
- [ ] Add behavior tests for anonymous exchange publishing.
- [x] Add behavior tests for `basic_get`.
- [x] Add behavior tests for `basic_consume` and `drain_events`.
- [x] Add behavior tests for `basic_ack`.
- [x] Add behavior tests for `basic_reject(requeue=True)` mapping to
  `Outcome.FAILED`.
- [x] Add behavior tests for `basic_reject(requeue=False)` mapping to
  `Outcome.REJECTED`.
- [ ] Add behavior tests for `no_ack=True` immediate acknowledgement.
- [x] Add behavior tests proving close with unacked messages does not republish.
- [ ] Add behavior tests for publish receipt success, failure, and timeout.
- [ ] Add behavior tests for Solace exceptions mapped to Kombu connection and
  channel errors.
- [x] Add behavior tests for optional management adapter behavior.

## Phase 2: Minimal Reliable Transport Implementation

- [x] Implement `kombu_solace.naming` for internal queue ingress topics.
- [x] Implement conservative wildcard helper for future native routing.
- [x] Implement `kombu_solace.serialization` envelope conversion.
- [x] Implement `kombu_solace.errors` and exception normalization.
- [x] Implement `kombu_solace.adapter.SolaceMessagingAdapter`.
- [x] Implement optional management adapter protocol with a no-management
  default.
- [x] Implement `kombu_solace.transport.Channel` with `do_restore = False`.
- [x] Implement `kombu_solace.transport.Transport`.
- [x] Register transport alias for process-local use.
- [x] Make current unit behavior tests pass.

## Phase 3: Broker Reliability Tests

- [x] Add opt-in integration tests gated by environment variables.
- [x] Document required Solace broker settings and permissions.
- [x] Test connect, declare queue, internal subscription, publish, consume, ack.
- [ ] Test unacked redelivery after receiver close/reconnect.
- [ ] Test NACK `FAILED` redelivery when broker supports settlement outcomes.
- [ ] Test NACK `REJECTED` discard or DMQ behavior when configured.
- [ ] Test publish receipt failure surfaces to Kombu.
- [x] Test SEMP size and purge against local broker.
- [ ] Test queue browser purge when enabled.
- [ ] Test reconnect or clean failure behavior.

## Phase 4: Performance and Soak

- [ ] Add opt-in benchmark test marker and command.
- [ ] Benchmark async publish throughput and latency.
- [ ] Benchmark sync publish latency.
- [ ] Benchmark consume/ack throughput.
- [ ] Measure publisher memory under back-pressure.
- [ ] Measure slow consumer memory under low prefetch.
- [ ] Measure multi-queue routing overhead in Kombu routing mode.
- [ ] Run long publish/consume soak with no unbounded memory growth.
- [ ] Record environment and broker details with results.

## Phase 5: Celery Compatibility

- [ ] Run a Celery worker smoke test with solo pool first.
- [ ] Document worker pool limitations from Solace multiprocessing constraints.
- [ ] Validate task publish, execute, ack, retry, and reject paths.
- [ ] Validate `acks_late=True` redelivery after worker interruption.
- [ ] Decide whether prefork support is impossible, unsupported, or requires a
  worker-process-local connection model.

## Open Decisions

- [x] Exact default namespace and internal topic encoding format.
- [ ] Default async publish in-flight limit and back-pressure buffer capacity.
- [ ] Whether `create_missing_queues` defaults to true for development or false
  for production safety.
- [x] Whether queue purge is disabled by default or best effort through queue
  browsing/receiver drain.
- [x] Which management adapter, if any, should be included first for durable
  queue delete/size.
- [ ] Whether native Solace routing is a v2 opt-in feature.
- [ ] Supported Python, Kombu, Celery, and Solace broker version floor.

## Definition of Done for First Release

- Direct and topic exchange behavior covered by unit tests.
- Close/unacked behavior covered and proven not to duplicate.
- Ack, reject/requeue, and reject/discard behavior covered.
- Publish receipt and back-pressure behavior covered.
- Solace adapter behavior covered without requiring a broker.
- Optional broker reliability tests documented and passing in a configured
  environment.
- Performance benchmark results recorded.
- Celery solo-pool smoke test documented.
- README clearly states supported and unsupported features.
