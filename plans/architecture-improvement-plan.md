# Architecture Improvement Plan

## Status

- Status: In progress
- Decision: Selected for incremental implementation
- Created: 2026-07-18
- Scope: End-to-end architecture, reliability, safety, operations, and testing

This document records the selected architecture direction. Each increment remains independently reviewable before the next one begins.

## Selected Constraints

- Deliver Phase 1 in small, independently verified increments.
- Preserve the behavior where a profile attaches to all matching devices.
- Match devices by keyboard name only; structured hardware selectors are deferred until needed.
- Remove the unused `dry_run` and `notifications` options instead of implementing them.
- Validate automated changes on a physical macropad after tests pass.

## Implementation Progress

### Phase 1, Increment 1: Completed

- Added regression coverage for generated profile serialization.
- Added regression coverage for independent keys within one debounce window.
- Added an explicit serializable configuration contract to handlers.
- Replaced the shared event timer and history with per-key state.
- Removed the unused shared debounce decorator.
- Verification: ten tests pass and all Python files compile.

### Phase 1, Increment 2: Completed

- Replaced event debounce threads with per-key monotonic deadlines.
- Replaced one-shot layer timer threads with monotonic deadlines.
- Added `Handler.tick()` and process due transitions from the device listener thread.
- Replaced timing sleeps in tests with an injected fake monotonic clock.
- Added coverage for deadline expiration and rescheduling from the latest event.
- Verification: twelve tests pass, all Python files compile, and no handler timer threads remain.

### Phase 1, Increment 3: Completed

- Added a typed `ProfileConfig` boundary between YAML parsing and runtime handlers.
- Added normalized `BindingConfig`, `LayerConfig`, and `KeyboardConfig` models.
- Moved shorthand expansion and inline-layer normalization into profile parsing.
- Changed `KeyboardHandler` to consume the combined `KeyboardConfig` without transforming or mutating it.
- Added source-aware validation for profile fields, versions, bindings, events, layers, actions, and internal handler commands.
- Added source-aware conflict diagnostics when merging profile fragments.
- Reject duplicate YAML keys with filename and line diagnostics.
- Made nested configuration mappings deeply immutable and multiprocessing-safe.
- Removed the unused `dry_run` and `notifications` runtime options.
- Migrated all seven active profiles to the current schema.
- Verification: twenty-eight tests pass and all active profiles validate and merge into three device configurations.

### Next Increment

Use `selectors` for device descriptors and rescan paths while other matching devices remain connected.

### Phase 2, Increment 1: Completed

- Watchdog callbacks now enqueue profile paths without mutating worker state.
- The main supervision loop is the sole owner of reload execution.
- Every profile file is parsed and every device configuration is merged before replacement begins.
- Invalid reload candidates leave all current workers running.
- Reload failures produce an error notification instead of a success notification.
- Verification: thirty-four tests pass, including reload ownership and validation-first replacement coverage.

### Phase 2, Increment 2: Completed

- Extracted profile preparation and worker lifecycle into `supervisor.py`.
- Added a `ProfileSupervisor` as the sole owner of process start, reload, health checks, joins, and shutdown.
- Workers are now indexed by device name in preparation for per-device reconciliation.
- Reduced `cli.py` to argument parsing, Watchdog setup, notifications, and main-loop dispatch.
- Added supervisor ownership, invalid-candidate preservation, and shutdown tests.
- Verification: thirty-seven tests pass with unchanged replace-all reload behavior.

### Phase 2, Increment 3: Completed

- Compare immutable merged device configurations during reloads.
- Keep unchanged workers running while starting added workers and stopping removed workers.
- Restart only workers whose configuration changed or whose process failed.
- Isolate worker startup failures so other device reconciliation continues.
- Refresh profile path metadata without restarting a worker when its configuration is unchanged.
- Verification: forty-three tests pass, all Python files compile, the patch has no whitespace errors, and the active user service loaded seven profile fragments into three device workers.

### Phase 2, Increment 4: Completed

- Retain each configured device as a worker slot while its process is running or waiting to retry.
- Add monotonic per-device restart delays of 1, 2, 4, 8, 16, and at most 30 seconds.
- Reset a device's backoff after its replacement process remains alive for thirty seconds.
- Preserve backoff across unchanged reloads, bypass it for changed configurations, and cancel it for removed devices.
- Keep failed process launches eligible for later retries without affecting healthy devices.
- Run the supervisor tick loop with or without Watchdog enabled.
- Remove the custom `SIGCHLD` reaper so `multiprocessing` can observe and collect worker exits.
- Track detached command subprocesses explicitly and reap completed commands from the worker loop.
- Add real-process coverage for worker exit detection and replacement.
- Verification: fifty-two tests pass, all Python files compile, and live fault injection restarted one killed worker after one second while another worker continued processing input.

### Phase 2, Increment 5: Completed

- Give every device worker a process-safe shutdown event.
- Exit listener loops cooperatively and close grabbed input devices through their cleanup path.
- Signal all workers before a shared five-second join window and force-kill only unresponsive processes.
- Convert CLI `SIGTERM` handling into an orderly main-loop exit and supervisor shutdown.
- Scope CLI signal handling to listen mode and route worker `SIGTERM` signals to their process-safe shutdown event.
- Keep an unkillable predecessor tracked and block its replacement from starting.
- Run the Python CLI directly as the systemd main process with mixed kill mode and a ten-second stop timeout.
- Add coverage for graceful reload replacement, device cleanup, real-process shutdown, CLI signal handling, and forced fallback.
- Verification: fifty-nine tests pass, all Python files compile, a systemd restart completes cleanly without status 143, and a directly signaled worker exits cooperatively before supervisor recovery.

### Package Structure Migration: Completed

- Moved application modules into the `src/macropad` package.
- Added module and `macropad` console entry points.
- Added the uv build backend and packaged application assets.
- Updated tests to import the installed package namespace.
- Updated Makefile and systemd generation to use the package entry point.
- Removed the obsolete `watch.sh` script.

## Current Architecture

```text
CLI -> Supervisor -> YAML profiles -> process per device -> evdev grab
                  -> keyboard handler -> detached shell commands

Profile watcher -> request queue -> CLI -> Supervisor reload
```

The project has a reasonable small-system flow, but device management, delayed key handling, process supervision, reloads, and command execution mutate live state across processes and threads without clear ownership.

## Original Findings

This table records the baseline findings. The implementation progress above is authoritative for findings that have since been resolved.

| Priority | Issue                                          | Impact                                                                                                                                                                                                             |
|----------|------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Critical | Profile generation is broken                   | `detect --generate-profile` raises `AttributeError` because `Profile.raw_data` expects `KeyboardHandler.raw_data`, which does not exist (`profile.py:13-23`, `main.py:239-251`).                                   |
| High     | Debouncing loses unrelated key actions         | `@debounce` has one timer shared by every invocation (`handlers.py:90-92`, `utils.py:22-43`). Pressing two multi-tap-capable keys within 200 ms cancels the first key.                                             |
| High     | Device identity can grab the wrong keyboard    | Generated profiles store only `device.name` (`profile.py:85-98`). Every device with that name is matched and grabbed (`interceptor.py:22-37`, `interceptor.py:90-105`).                                            |
| High     | Reloading is destructive and non-transactional | Reload stops every working process before validating replacements (`main.py:152-158`). One invalid fragment can disable an otherwise working device profile.                                                       |
| High     | Reload state has multiple concurrent owners    | Watchdog invokes reload from its thread (`main.py:19-35`), while the main supervision loop can invoke it concurrently (`main.py:205-213`). Both mutate the same process list.                                      |
| High     | Invalid actions can kill a device worker       | Profiles are raw dictionaries with little validation (`profile.py:36-42`). Malformed directives can raise `IndexError` (`handlers.py:233-243`), while invalid action types can fail in `Popen` (`utils.py:48-62`). |
| Medium   | Hotplug handling is incomplete                 | Device scanning only happens when no matching device remains (`interceptor.py:87-106`). A disconnected path is not reacquired while another matching path remains active.                                          |
| Medium   | Event handling is racy                         | Debounce and layer expiration use `threading.Timer` while the listener mutates the same layer and event-history fields (`handlers.py:44-53`, `handlers.py:149-193`).                                               |
| Medium   | Shell execution is unbounded and opaque        | Every action starts a detached `shell=True` process with output discarded (`utils.py:48-60`). Rapid repeats can create many processes, and failures are not observable.                                            |
| Medium   | Configuration options are misleading           | `dry_run` and `notifications` are loaded but not honored (`handlers.py:51-52`). Profile versions are inconsistently typed and never validated.                                                                     |
| Medium   | Process supervision is fragile                 | A custom `SIGCHLD` reaper overlaps with `multiprocessing.Process` lifecycle handling (`main.py:149`, `utils.py:12-19`). Shutdown uses abrupt termination.                                                          |
| Medium   | Failures may exit successfully                 | Missing profiles print an error and return status zero (`main.py:178-180`). Non-ENODEV `OSError` instances are swallowed (`main.py:224-226`).                                                                      |
| Low      | Packaging and operations are incomplete        | There is no declared CLI entry point or build backend. The systemd instructions name targets that do not exist (`Makefile:38-43`), and `watch.sh` is stale.                                                        |
| Low      | Observability is insufficient                  | Multi-process `print` output lacks levels and consistent context. Command output, exit status, restart count, and reload failures are unavailable.                                                                 |

## Original Baseline

- `detect --generate-profile` reaches an `AttributeError` during profile serialization.
- Pressing two different multi-tap-capable keys inside the debounce window executes only the second key's action.
- All seven existing tests pass in approximately 1.11 seconds.
- Python compilation succeeds.
- `uv.lock` is consistent.
- Existing tests cover only one-shot layer behavior in `tests/test_handlers.py`.

## Proposed Architecture

```text
CLI
  -> ConfigLoader: parse, validate, merge immutable configurations
  -> Supervisor: sole owner of worker lifecycle and reload state
      -> DeviceWorker
          -> DeviceSession
          -> BindingEngine
          -> ActionExecutor

Watcher -> ReloadRequest queue -> Supervisor
```

### Config Loader

Parse and validate complete candidate configurations before changing live workers. Return immutable, typed configuration objects and errors containing the source file and binding path.

### Supervisor

Make one component solely responsible for starting, stopping, replacing, and monitoring workers. Watcher and signal callbacks should enqueue requests rather than mutate processes directly.

### Device Session

Own device descriptors, grabs, and reconnect behavior. Device matching remains name-only until a concrete need for structured hardware selectors emerges.

### Binding Engine

Use a deterministic state machine with per-key state and monotonic timestamps. It should emit actions without executing side effects. Delayed decisions should run on the event-loop thread rather than `threading.Timer` threads.

### Action Executor

Control subprocess concurrency, dry-run behavior, logging, completion, and shutdown. Existing command strings can remain trusted shell actions for configuration compatibility, while explicit argument-array actions can be supported for safer execution.

## Roadmap

### Phase 1: Correctness and Safety

1. [x] Fix profile serialization and add a generated-profile regression test.
2. [x] Replace the global debounce timer with per-key state.
3. [x] Run key-state transitions on one thread using monotonic deadlines or `tick(now)`
4. [x] Add dataclass-based profile validation with precise diagnostics.
5. [x] Remove the unused `dry_run` and `notifications` options.
6. Deferred: keep name-only matching and revisit structured selectors if a concrete need emerges.

### Phase 2: Runtime Reliability

1. [x] Queue watcher events instead of reloading from the watcher thread.
2. [x] Validate and merge the complete candidate configuration before stopping workers.
3. [x] Restart only the failed or changed device worker.
4. [x] Add per-device exponential restart backoff.
5. [x] Replace abrupt termination with a shutdown event and bounded join.
6. [x] Remove the custom `SIGCHLD` reaper and let the supervisor collect children.
7. Use `selectors` for device descriptors and rescan paths even when other devices remain connected.

### Phase 3: Commands and Operations

1. Add a bounded action executor that tracks subprocesses and logs exit status.
2. Preserve trusted shell-string actions for compatibility and support explicit argument-array actions.
3. Use Python logging with device, profile, key, and worker context.
4. Return nonzero exit codes for startup and configuration failures.
5. Add a real `[project.scripts]` entry point and a checked-in systemd unit template.
6. [x] Remove or repair `watch.sh` and align the Makefile target names.

### Phase 4: Testing and CI

Add deterministic coverage for:

- Generated profile serialization.
- Independent simultaneous keys and tap timing.
- Hold and repeat behavior.
- Profile validation and fragment conflicts.
- Transactional reload failure.
- Partial device disconnect and reconnect.
- Worker failure and restart backoff.
- Command failure, dry-run behavior, and concurrency limits.
- Wheel installation in a clean virtual environment.
- Console and `python -m macropad` entry points from an installed wheel.
- Packaged asset availability outside the source checkout.
- Generated systemd unit validation and service startup smoke testing.

Add CI for supported Python versions with unit tests, integration tests, wheel building, compilation, linting, and lockfile validation.

## Decision Criteria

Before selecting this plan, compare it with alternatives using these criteria:

- Risk reduction for accidental device grabs and lost actions.
- Compatibility with existing profile files.
- Implementation size and migration complexity.
- Ability to test behavior without physical hardware.
- Operational reliability under systemd.
- Ongoing maintenance cost.

## Suggested First Increment

If this plan is selected, start with the smallest independently valuable increment:

1. Add failing regression tests for profile generation and independent-key debounce.
2. Fix only those two defects.
3. Validate behavior on a physical macropad before starting the supervisor redesign.
