# Macropad Runtime Architecture

This directory contains the complete runtime implementation for Macropad. Runtime domains use a
flat module layout, while the `cli/` package groups command-specific orchestration behind a small
argument-parsing and dispatch boundary.

This document is the architecture reference for contributors. Update it whenever module ownership,
dependency direction, process lifecycle, or the profile and event flows change.

## Module Map

| Module                 | Responsibility                                                                                                                         |
|------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| `__main__.py`          | Implements the `python -m macropad` entry point by delegating to `cli.main()`.                                                         |
| `cli/__init__.py`      | Parses arguments, dispatches commands, and handles process-wide command errors.                                                        |
| `cli/listen.py`        | Coordinates listener startup, profile reloads, the parent supervision loop, and top-level shutdown.                                    |
| `cli/doctor.py`        | Renders read-only environment diagnostics and returns status based on blocking results.                                                |
| `cli/init.py`          | Orchestrates guided input checks, device/key capture, collision-safe fragment creation, and generated-profile validation.              |
| `cli/monitor.py`       | Lists readable devices and renders non-grabbing key-event streams.                                                                     |
| `cli/status.py`        | Queries and renders live parent, worker, device, retry, and configuration state.                                                       |
| `cli/validate.py`      | Resolves validation inputs and delegates the standalone validation workflow.                                                           |
| `cli/profile_files.py` | Owns the default configuration path and discovers unique profile files for CLI commands.                                               |
| `cli/service.py`       | Runs service command actions through explicit `systemctl --user` and `journalctl --user` invocations.                                  |
| `service_unit.py`      | Resolves installed executable and XDG unit paths, renders generated units, and safely installs or removes owned unit files.            |
| `profile_watcher.py`   | Adapts Watchdog events, manages the polling observer, and schedules trailing-edge profile reloads.                                     |
| `runtime_status.py`    | Owns the secured local Unix status endpoint, client transport, and runtime path resolution.                                            |
| `diagnostics.py`       | Classifies input access, profiles, notifications, installation paths, and environment checks.                                          |
| `validation.py`        | Loads complete validation candidates, collects file and merged errors, and renders validation reports.                                 |
| `config.py`            | Defines the deeply immutable, picklable profile configuration model and validation error type.                                         |
| `profiles.py`          | Loads strict YAML and validates, normalizes, groups, and merges profile configurations.                                                |
| `supervisor.py`        | Reconciles desired profiles with worker slots, owns child processes, applies restart backoff, and enforces bounded shutdown.           |
| `worker.py`            | Defines the child-process entry point, installs the worker signal handler, constructs the keyboard handler, and owns handler shutdown. |
| `interceptor.py`       | Discovers evdev devices, detects newly connected keyboards, grabs matching event nodes, and forwards input events to a handler.        |
| `handlers.py`          | Resolves key events, tap and hold sequences, layers, and internal handler commands into action submissions.                            |
| `actions.py`           | Starts trusted shell actions as detached processes and enforces the per-worker concurrency limit.                                      |
| `notifications.py`     | Lazily imports the optional desktop backend, caches unavailability per process, and sends notifications when enabled.                  |
| `logging_config.py`    | Selects normal, verbose, or debug levels and renders structured context fields consistently.                                           |
| `assets/`              | Contains package resources, currently the desktop notification icon.                                                                   |

## Dependency Diagram

```mermaid
flowchart TD
    Entrypoints[macropad and python -m macropad] --> CLI[cli/__init__.py]
    CLI --> Listen[cli/listen.py]
    CLI --> Doctor[cli/doctor.py]
    CLI --> Init[cli/init.py]
    CLI --> Monitor[cli/monitor.py]
    CLI --> Status[cli/status.py]
    CLI --> ValidateCommand[cli/validate.py]
    CLI --> Service[cli/service.py]

    Listen --> ProfileFiles[cli/profile_files.py]
    Listen --> ProfileWatcher[profile_watcher.py]
    Listen --> Supervisor[supervisor.py]
    Listen --> Notifications[notifications.py]
    Listen --> RuntimeStatus[runtime_status.py]

    Doctor --> Diagnostics[diagnostics.py]
    Doctor --> ProfileFiles
    Doctor --> Service
    Diagnostics --> Interceptor[interceptor.py]
    Diagnostics --> Notifications

    Init --> Diagnostics
    Init --> Interceptor
    Init --> ProfileFiles
    Init --> Profiles
    Init --> Validation
    Init --> Service

    Monitor --> Interceptor
    Status --> RuntimeStatus
    Status --> Service

    ValidateCommand --> ProfileFiles
    ValidateCommand --> Validation[validation.py]

    Supervisor --> Profiles
    Supervisor --> Worker[worker.py]
    Supervisor --> Interceptor

    Validation --> Profiles
    Validation --> Config
    Profiles --> Config[config.py]
    ProfileWatcher --> Watchdog[watchdog]
    Service --> Systemd[systemctl]
    Service --> Journal[journalctl]
    Service --> ServiceUnit[service_unit.py]
    ServiceUnit --> UnitFile[generated user unit]

    Worker --> Handler[handlers.py]
    Worker --> Interceptor
    Worker --> Actions
    Worker --> StatusQueue[worker status queue]
    Supervisor --> StatusQueue

    Handler --> Config
    Handler --> Actions[actions.py]
    Handler --> Notifications

    Interceptor --> Evdev[evdev]
    Actions --> Shell[detached shell processes]
    Notifications -. optional .-> Notify2[notify2 and DBus]
```

Dependencies should continue to point inward toward immutable configuration and outward toward
system adapters. In particular:

- `profiles.py` must remain independent of worker, handler, process, and device state.
- `profile_watcher.py` owns filesystem event filtering and reload timing but never reloads profiles.
- `diagnostics.py` classifies checks but leaves evdev and systemd resource ownership in their
  existing adapters.
- `cli/service.py` owns systemd and journal subprocess invocation but no daemon runtime state;
  `service_unit.py` owns unit rendering and filesystem changes without invoking systemd.
- `supervisor.py` owns processes but does not process keyboard events.
- `worker.py` is the boundary where immutable configuration becomes mutable runtime state.
- `interceptor.py` owns evdev resources but does not construct or shut down handlers.
- `handlers.py` may submit actions and notifications but must not manage worker processes.
- `actions.py`, `notifications.py`, and `interceptor.py` are adapters to operating-system services;
  the notification adapter must remain importable without its optional backend dependencies.

## Process Model

The CLI runs in the parent process. `ProfileSupervisor` maintains one worker slot for each configured
keyboard name. Each slot has its own `multiprocessing.Process`, shutdown event, restart counters, and
retry deadline.

Only immutable `ProfileConfig` data, logging and notification option booleans, a worker generation
ID, and the shared status queue cross the process boundary. The
parent does not construct a `KeyboardHandler` or `ActionExecutor`. The child enters through
`worker.run()`, configures its own logging so non-fork start methods behave consistently, installs its
SIGTERM handler, constructs the executor and handler, and then enters the interception loop. This
keeps mutable resources owned by the process that uses them and avoids requiring runtime objects to
be serialized.

The project is Linux-only. Device identity is the evdev keyboard name, and one worker attaches to all
current `/dev/input/event*` nodes with that name.

## Startup Flow

1. `cli.main()` parses global logging and notification options, configures process-wide preferences,
   and dispatches to the focused `doctor`, `init`, `listen`, `monitor`, `validate`, or `service`
   command module.
2. `cli.listen.run()` installs the parent SIGTERM handler without importing the optional notification
   backend.
3. `cli.profile_files` resolves explicit profile paths and all `.yml` files in requested profile
   directories.
4. `ProfileSupervisor.start()` calls `prepare_profiles()` before starting any process.
5. Every YAML file is loaded and validated before fragments are merged by keyboard name.
6. The supervisor creates one worker slot per merged `ProfileConfig` and starts `worker.run()` in a
   child process, forwarding logging level and action-output options.
7. The worker configures logging, constructs `ActionExecutor` and `KeyboardHandler`, then calls
   `interceptor.listen()`.
8. The interceptor waits for matching devices, opens and grabs every matching event node, and begins
   forwarding input events.
9. The worker publishes deduplicated state transitions to the parent, which serves snapshots through
   the local runtime status socket.

`cli.profile_files` resolves the default directory from an absolute `XDG_CONFIG_HOME`, falling back
to `~/.config` when it is unset or invalid. If a custom XDG profile directory is absent but the
legacy `~/.config/macropad/profiles/` directory exists, the legacy path remains active until the XDG
directory is created. No files are migrated automatically.

If the resolved default configuration directory contains profiles, the CLI automatically enables
profile watching. If it does not exist or contains no YAML files, startup fails with profile-format
guidance without creating directories or example files.

The validation command module delegates to `validation.run()`, which uses the same complete load,
validation, grouping, and merge path as worker startup, but never initializes notifications,
constructs a supervisor, or opens an input device. Semantic checks that depend on the complete device
configuration, including layer references, run after fragments for that device are merged.

## Guided Initialization Flow

`cli.init` is interactive orchestration over existing adapters and profile APIs; it does not own
evdev handles or duplicate profile merge rules.

1. Read systemd service state and render the blocking input checks from `diagnostics.py`.
2. Ask the user to disconnect the target, then call the non-grabbing `interceptor.detect()` under a
   monotonic timeout while the user reconnects it and presses a key.
3. Load and merge current default-directory profiles. For an already-profiled device, list its
   fragment paths and require confirmation before proposing another fragment.
4. If that key's release event is already bound, call `interceptor.capture_key()` to wait for release
   and capture a different key from the same device.
5. Validate the proposed fragment together with all loaded profiles in memory.
6. Select a slug-based filename with a numeric collision suffix, create it exclusively, and run the
   normal complete validation workflow against the on-disk directory.
7. Remove only the generated file on cancellation or any write or validation failure. On success,
   report the exact path, refresh service state, qualify watch behavior when effective arguments are
   unknown, and show the next foreground or service command.

## Input And Action Flow

```mermaid
sequenceDiagram
    participant Device as evdev device
    participant Interceptor as interceptor.listen
    participant Handler as KeyboardHandler
    participant Context as context shell command
    participant Executor as ActionExecutor
    participant Shell as detached shell process

    Device->>Interceptor: InputEvent
    Interceptor->>Handler: handle(event)
    Interceptor->>Handler: tick()
    Handler->>Context: query application ID on initial key press
    Context-->>Handler: output within 100 ms or fallback
    Handler->>Handler: resolve manual, context, or base layer and event state
    Handler->>Executor: submit(command)
    Executor->>Shell: Popen(shell=True, start_new_session=True)
    Interceptor->>Handler: tick on later loop iterations
    Handler->>Executor: tick()
    Executor->>Executor: reap completed actions
```

Simple `up` or `down` bindings can execute immediately. Bindings involving hold, double-tap, or
triple-tap resolution use the profile's `multi_tap_ms` monotonic deadline and are advanced by
`KeyboardHandler.tick()` on the listener thread. One-shot layers use `one_shot_timeout_ms` through
the same threadless mechanism. Omitted timing fields retain the 200 ms and 5,000 ms defaults. Hold
recognition deliberately remains based on evdev kernel-repeat events rather than elapsed time.

Manual layers resolve first, followed by the command-selected context layer and then base bindings.
Each `LayerConfig` stops fallback when set to `fallback: none`. Context commands are trusted shell
strings run synchronously with captured output and a 100 ms timeout only on initial key presses; the
resolved context is latched through repeats and release. Command failure or unknown output continues
with normal lookup. One-shot claims occur after binding resolution, so an executed context or base
fallback consumes the one-shot layer. Toggle and momentary activation-key events are intercepted
before normal lookup: toggle release always deactivates its layer, while momentary release restores
an immutable snapshot of the previous layer state. Nested snapshots discard states whose activation
keys were released while hidden. Every transition increments the layer generation, preventing pending
events from a replaced manual layer from executing later. Momentary transitions are intentionally
excluded from desktop notifications.

Actions are trusted shell strings. Each worker may have at most eight active actions; additional
actions are dropped rather than queued and logged with the active count and limit. Action processes
are detached and are not terminated when a worker reloads or stops. Normal mode routes stdout and
stderr to `/dev/null`; action-debug mode inherits the worker streams so foreground output remains in
the terminal and service output reaches the journal.

The handler passes resolved device, key, event, and base or named layer context into each submission.
The executor retains that trigger context through command start, process ID, exit status, and
concurrency rejection records, including when identical commands run concurrently. Debug startup
logging reports only the action working directory, `PATH`, display names, DBus presence, and output
mode rather than dumping the full environment or DBus address.

Notification preference is passed through `ProfileSupervisor` to every worker so spawn and fork
process starts behave consistently. Each process imports and initializes `notify2` only on its first
notification attempt. Missing dependencies, initialization failure, or send failure disables later
attempts in that process after one warning. `--no-notifications` avoids backend import entirely; when
used with `service install`, the generated unit retains that global option.

The generated systemd user unit gives actions a deterministic `PATH` containing `~/bin`,
`~/.local/bin`, and standard system command directories. It invokes the console script from the
environment that installed the unit and intentionally does not start Macropad through a login shell.
The unit is ordered after and bound to `graphical-session.target`, allowing graphical actions to
inherit the desktop environment without depending on a specific desktop environment.

## Service Installation Flow

`cli.service.install()` asks `service_unit.py` to resolve the console script beside the active Python
environment, resolve the user unit path from an absolute `XDG_CONFIG_HOME` or `~/.config`, and render
the unit. The unit file is replaced atomically only when absent, marked as generated by Macropad, or
explicitly forced. The CLI then reloads systemd, enables the unit, and starts it.

Uninstall validates the same marker before stopping anything, stops and disables the unit, removes
it, and reloads systemd. It never removes package files or profiles. Development checkouts and
installed tools use this same path; `make test-systemd` only validates production renderer output.

## Device Lifecycle

`matching_device_paths()` enumerates evdev paths, opens each path long enough to inspect its name, and
closes every probe. Paths that disappear during enumeration are ignored. Permission failures and
other open errors are logged once per unresolved operation and path rather than silently treated as
an absent device or repeatedly flooding the journal.

The listener opens and exclusively grabs all paths matching the configured keyboard name. When a
path reports `ENODEV`, it is closed and removed. The listener rescans only after every matching path
has gone; it intentionally does not acquire an additional path while another matching path remains
connected.

`probe_device_access()` briefly opens, grabs, ungrabs, and closes each current event device for
`macropad doctor`. It records `EACCES`, `EBUSY`, `ENODEV`, and other operation failures as data so the
diagnostic workflow can provide remediation without leaking handles. Runtime grab conflicts and
permission failures are logged distinctly before a worker exits or continues scanning.
An `EBUSY` probe is a nonblocking warning when the Macropad user service is active and a blocking
failure otherwise; stopping the service and rerunning the check disambiguates ownership.

`interceptor.monitor()` opens every current path matching an exact device name without calling
`grab()`. It rescans while other paths remain connected, reports each connection and disconnection,
and reacquires matching paths after reconnect. This monitoring behavior is independent from the
listener's intentional policy of rescanning only after all matching paths are gone.
The command reports when the Macropad service is active because its configured devices are already
exclusively grabbed and cannot deliver events to the non-grabbing monitor until the service stops.

`interceptor.listen()` reports `opening` before attempting handles, `listening` only after successful
grabs, `waiting` after all grabbed paths disappear, and path-specific input errors. `worker.run()`
adds initial `waiting`, fatal `error`, and cooperative `shutting_down` transitions. Each message
contains the worker generation ID so updates from a replaced process cannot overwrite its successor.

## Runtime Status Flow

The parent owns the only external endpoint. Workers cannot accept status clients and status clients
cannot mutate daemon state.

```mermaid
sequenceDiagram
    participant Worker
    participant Queue as Multiprocessing status queue
    participant Parent as ProfileSupervisor
    participant Socket as Local Unix socket
    participant Client as macropad status

    Worker->>Queue: waiting/opening/listening/error update
    Parent->>Queue: Drain generation-tagged updates
    Parent->>Parent: Merge process, retry, profile, and reload state
    Parent->>Socket: Publish immutable snapshot before blocking transitions
    Client->>Socket: Connect read-only
    Socket-->>Client: Parent and worker status
```

The socket lives under `$XDG_RUNTIME_DIR/macropad/status.sock`, falling back to a user-specific
temporary directory. Runtime directories are verified as user-owned and forced to mode `0700`; the
socket and lifetime lock use mode `0600`. The lock serializes listener startup. Stale and owned socket
cleanup keeps an `O_PATH` descriptor open while comparing device/inode identity, preventing inode
recycling from making a replacement look like the original; a regular file is never removed as a
stale socket. A small read-only server thread keeps the latest parent-published snapshot available
while the parent waits for workers to stop. Closing the parent attempts to remove only the socket
inode it created; cleanup errors are logged without preventing socket and lock handles from closing.

The internal `detect()` helper snapshots existing paths, waits for a new path even when another
device disappears at the same time, and returns the new keyboard's name, event path, and first
pressed `KEY_*` name. One monotonic deadline bounds both reconnect and key capture. `capture_key()`
uses the same non-grabbing handle lifecycle for another key on a known device, but waits for held keys
to be released before accepting another press. Probe handles are always closed before either helper
returns or times out. These helpers are used by guided initialization rather than exposed as
standalone commands.

## Profile Reload Flow

The Watchdog polling observer runs in a background thread, but it never reloads configuration itself.
It inspects both source and destination paths for each event and places every relevant `.yml` path
into a queue owned by `cli.listen`. This catches direct writes, create/delete events, profile renames,
and atomic saves that move a temporary file onto a profile.

```mermaid
sequenceDiagram
    participant Watchdog
    participant Queue as Reload queue
    participant CLI as cli.listen parent loop
    participant Scheduler as Reload scheduler
    participant Supervisor as ProfileSupervisor

    Watchdog->>Queue: Changed source/destination .yml path
    CLI->>Queue: Drain pending paths
    Queue-->>CLI: Event burst
    CLI->>Scheduler: Add paths at monotonic time
    Note over Scheduler: Deduplicate paths and reset one-second deadline
    CLI->>Scheduler: Check deadline each supervision cycle
    Scheduler-->>CLI: Paths after a quiet second
    CLI->>Supervisor: Reload complete current profile set
```

The scheduler is owned by the parent loop. Every new batch moves its monotonic deadline forward, so
reload happens only after one quiet second. The resulting changed-path list is deduplicated and
included in reload success and failure logs.

Reload follows a validate-then-reconcile model:

1. Load and validate the complete candidate file set.
2. Merge all fragments by keyboard name.
3. Leave workers with equal immutable configuration running, updating only their source paths.
4. Stop workers for removed or changed configurations.
5. Start workers for added or changed configurations.
6. Preserve independent failure and restart state for unchanged workers.

An invalid candidate fails before reconciliation, so currently running workers remain intact.

## Failure And Shutdown Behavior

The supervisor checks workers once per parent loop iteration. A failed worker receives exponential
restart backoff from one second up to thirty seconds. After thirty stable seconds, its failure count
is reset. One failed keyboard does not restart healthy workers.

Parent shutdown sets every worker shutdown event and waits up to five seconds across the worker set.
Workers cooperatively leave the listener loop, close all evdev handles, and shut down their handler.
Processes that do not stop are killed and joined for one additional second. A process that survives
the kill is reported as a shutdown failure.

Desktop notification initialization and delivery are both optional. Failures are logged and never
prevent headless startup or event handling.

## Configuration Ownership

`config.py` contains only immutable value objects:

- `ProfileConfig` owns the device name, profile version, keyboard configuration, diagnostic source,
  deferred layer-reference paths, and explicit timing-field metadata used by merged validation.
- `KeyboardConfig` owns base bindings, named layers, effective timing, and optional context
  configuration.
- `ContextConfig` owns the trusted application query command and exact output-to-layer mappings.
- `TimingConfig` owns the multi-tap resolution and one-shot layer deadlines in milliseconds.
- `LayerConfig` owns layer bindings, effective base-fallback policy, and whether that policy was
  explicitly configured for fragment merging.
- `BindingConfig` maps event names to command tuples.
- `FrozenDict` prevents nested mutation while keeping configurations comparable, hashable, and
  picklable.

`profiles.py` is the only module that converts untrusted YAML-shaped data into these objects. Keep
source names and field paths in every validation error because reload diagnostics depend on them.

## Extension Guidelines

- Add profile schema behavior in `profiles.py` and immutable values in `config.py`.
- Add keyboard event semantics in `handlers.py` and use fake monotonic clocks in tests.
- Add evdev discovery or handle behavior in `interceptor.py` without moving process policy there.
- Add worker process setup or cleanup in `worker.py`.
- Add live worker state transitions in `worker.py` and `interceptor.py`, parent snapshots in
  `supervisor.py`, and local transport behavior in `runtime_status.py`.
- Add reconciliation, restart, or bounded-shutdown policy in `supervisor.py`.
- Add Watchdog event handling, observer lifecycle, or reload debounce behavior in
  `profile_watcher.py`.
- Add systemd lifecycle or journal command behavior in `cli/service.py`.
- Add guided profile-creation policy in `cli/init.py`, reusing diagnostics, interceptor, and profile
  validation APIs rather than moving their ownership into the command module.
- Add diagnostic checks and remediation in `diagnostics.py`, keeping command rendering in
  `cli/doctor.py` and operating-system resource handling in the owning adapter.
- Add device and key presentation in `cli/monitor.py`, keeping evdev resources and reconnect behavior
  in `interceptor.py`.
- Add argument parsing and dispatch in `cli/__init__.py`, and command-specific orchestration in a
  focused module under `cli/`.
- Add global logging level behavior in `logging_config.py` and pass action-output policy through the
  supervisor to the worker-owned `ActionExecutor`.
- Add validation workflow or report behavior in `validation.py`, keeping schema and merge rules in
  `profiles.py`.
- Keep operating-system adapters optional or failure-tolerant where the service can continue without
  them.

Unit tests mirror flat runtime modules under `tests/test_*.py` and CLI modules under `tests/cli/`.
Packaging and lifecycle smoke tests live under `tests/integration/` and are intentionally excluded
from normal unit-test discovery.
