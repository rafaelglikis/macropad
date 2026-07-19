# Macropad UX And Product Improvement Plan

## Purpose

Turn the current reliable runtime into a product that is safe and understandable to install,
configure, diagnose, and operate. Work through this plan in order, completing one independently
shippable item at a time.

## Working Agreement

- Mark an item complete only after its implementation, tests, and documentation are complete.
- Keep each item focused; do not pull later product features into earlier reliability work.
- Preserve name-only device identity and all current matching-path behavior until item 14 has a
  concrete requirement.
- Preserve trusted detached shell-string actions and the eight-action limit unless a plan item
  explicitly changes their user-facing behavior.
- Do not modify profiles under `~/.config/macropad/profiles/` while implementing or testing.
- Update `src/macropad/README.md` whenever module ownership, process lifecycle, dependency
  direction, or runtime flow changes.
- Before completing Python changes, run `make format`, `make lint`, and `make test` in that order.
- Run the relevant integration checks for packaging, service, and systemd changes.

## Current Baseline

Macropad already provides:

- Strict version 1 YAML profiles with source and field-path diagnostics.
- Base bindings, persistent and one-shot layers, and up/down/hold/multi-tap events.
- Profile fragments merged by keyboard name.
- Validate-before-reconcile profile reloads that retain the last valid configuration.
- One isolated worker process per keyboard with restart backoff.
- Device disconnect/reconnect handling and bounded graceful shutdown.
- Trusted detached shell actions with bounded concurrency.
- Optional-at-runtime desktop notifications and a systemd user service.

## Implementation Order

### 1. Expose Profile Validation And Document The Schema

Status: [x] Complete

Goal: Let users validate and understand profiles without starting the daemon or grabbing a device.

Deliverables:

- Add `macropad validate` for explicit files, profile directories, and the existing default profile
  directory.
- Never create a configuration directory or sample profile during validation.
- Return zero only when the complete candidate profile set loads, validates, and merges.
- Preserve file and field-path diagnostics in terminal output.
- Validate layer references after fragments are merged so a layer may be defined in another
  fragment, but a genuinely missing layer fails validation.
- Reject or clearly diagnose a merged device configuration with no reachable base actions.
- Add a user-facing profile reference to the root documentation with examples for shorthand,
  command lists, every event type, top-level layers, inline layers, persistent layers, one-shot
  layers, fragments, and merge conflicts.
- Document that profile actions are trusted shell code, run from `/`, inherit the service
  environment, are detached, and may be dropped at the concurrency limit.

Acceptance criteria:

- Valid profiles produce a short success summary containing profile and device counts.
- Invalid YAML, unknown keys/events, merge conflicts, missing layers, and empty effective profiles
  return a nonzero status with actionable diagnostics.
- Validation never opens or grabs an input device.
- CLI help contains examples or points directly to the profile reference.

Verification:

- Add focused CLI and profile unit tests.
- Run `make format`, `make lint`, and `make test`.

### 2. Make Profile Watching Reliable For Real Editors

Status: [x] Complete

Goal: Ensure every completed save eventually reloads exactly the latest complete profile set.

Deliverables:

- Replace the current leading-edge global debounce with trailing-edge reload scheduling owned by
  the CLI supervision loop.
- Recognize both source and destination paths for moved files so atomic saves are detected.
- Handle create, modify, move, delete, truncate-and-write, and rapid multi-file edits.
- Coalesce a burst into one full candidate reload after the quiet period without discarding the
  final event.
- Keep the current last-valid-configuration behavior when a candidate is invalid.
- Include changed paths in success and failure diagnostics.

Acceptance criteria:

- Atomic rename saves reload successfully.
- A partial write followed quickly by a complete write ends on the complete configuration.
- Rapid changes to multiple profile files result in one reload of the final directory state.
- Invalid reloads do not stop or replace current healthy workers.

Verification:

- Add deterministic watcher tests with fake monotonic time; do not use sleeps in unit tests.
- Run `make format`, `make lint`, `make test`, and `make test-service`.

### 3. Remove Misleading First-Run Sample Behavior

Status: [x] Complete

Goal: Never report a healthy setup by running a worker for a fake keyboard.

Deliverables:

- Remove automatic configuration-directory and sample-profile creation from `listen`.
- Stop starting a worker for a fake `Sample Device` when no real profiles exist.
- When no profiles exist, return an actionable message pointing to the expected location and profile
  documentation.
- Remove the public `detect` and `detect --generate-profile` surface rather than maintaining a
  temporary profile-generation workflow that `monitor` and `init` will replace.
- Retain low-level device detection only as an internal primitive for the guided initialization flow.
- Remove unused sample serialization code and its `notify-send` dependency.

Acceptance criteria:

- `listen` with no profiles creates no directories or files and does not wait for a fake device.
- The public CLI no longer advertises `detect` or profile generation.
- Existing profile files are never modified.

Verification:

- Add tests using an isolated temporary configuration directory.
- Run `make format`, `make lint`, and `make test`.

### 4. Add Permission And Environment Diagnostics

Status: [x] Complete

Goal: Explain why Macropad cannot see or grab a keyboard before the service is started.

Deliverables:

- Add `macropad doctor` with checks for input-device enumeration, open/read access, exclusive-grab
  conflicts, profile-directory access, notification availability, executable/service paths, and
  relevant environment variables.
- Stop silently treating `EACCES` and other meaningful device-open errors as "device absent."
- Distinguish missing devices, permission failures, disappearing devices, and `EBUSY` grab
  conflicts in logs and CLI output.
- Add Debian/Ubuntu and Fedora permission guidance, including the security implications of input
  access.
- Make notification failures informational when notifications are not required.

Acceptance criteria:

- Every failed check has a concise explanation and remediation.
- The command returns nonzero for conditions that prevent listening and zero when only optional
  capabilities are unavailable.
- Running the command never permanently grabs a keyboard or starts actions.

Verification:

- Unit-test `EACCES`, `EBUSY`, `ENODEV`, missing directories, and unavailable DBus behavior.
- Run `make format`, `make lint`, and `make test`.

### 5. Add Safe Device And Key Monitoring

Status: [x] Complete

Goal: Let users identify device names and `KEY_*` codes without disabling their keyboard.

Deliverables:

- Add a monitor command that lists readable input devices and can stream key names for a selected
  device without exclusive grabbing by default.
- Make explicit when multiple event paths share the selected keyboard name.
- Add an explicit opt-in grab mode only if it provides useful parity testing.
- Display down, repeat/hold, and up events in a compact format.
- Support clean cancellation and device disconnect/reconnect feedback.

Acceptance criteria:

- A user can discover the exact profile device name and key names without editing YAML first.
- Default monitor mode does not suppress normal keyboard input.
- Name collisions and permission failures are visible.

Verification:

- Add adapter-level tests for output, reconnects, collisions, and cancellation.
- Run `make format`, `make lint`, and `make test`.

### 6. Provide A Guided Initialization Flow

Status: [x] Complete

Goal: Take a new user from installation to one working macro with no unexplained manual steps.

Deliverables:

- Add `macropad init` that performs relevant doctor checks, explains reconnect detection, detects a
  keyboard, records at least one key, asks for an initial command, writes a profile, validates it,
  and shows the next foreground/service command.
- Explain that users must connect or reconnect a device after detection starts and then press a key.
- Provide clear cancellation and timeout behavior instead of waiting silently forever.
- Confirm the exact generated path and whether profile watching will pick it up.

Acceptance criteria:

- The flow never overwrites a profile without explicit confirmation.
- Canceling leaves no partial files.
- Generated content passes `macropad validate` before success is reported.

Verification:

- Unit-test success, cancellation, timeout, collisions, and validation failure.
- Add a lightweight integration test that uses mocked input discovery and a temporary config root.
- Run `make format`, `make lint`, and `make test`.

### 7. Improve Runtime And Action Debugging

Status: [x] Complete

Goal: Make "the key did nothing" diagnosable without reading source code.

Deliverables:

- Add global `--verbose` and `--debug` logging controls.
- Add an explicit action-debug mode that routes action output to the foreground terminal or systemd
  journal instead of `/dev/null`.
- Log resolved device, key, event, layer, command start, exit status, concurrency rejection, and
  relevant action environment without exposing unnecessary secrets.
- Document differences between an interactive shell and the systemd service environment,
  especially `PATH`, display/session variables, and the `/` working directory.
- Make action drops at the concurrency limit visible enough to explain missed macros without
  generating a notification storm.

Acceptance criteria:

- Normal mode remains concise and preserves current detached action behavior.
- Debug mode shows why an action failed, including stderr when enabled.
- Logging options work consistently for both entry points.

Verification:

- Add logging and action-output tests.
- Run `make format`, `make lint`, `make test`, and `make test-service`.

### 8. Add Trustworthy Runtime Status

Status: [x] Complete

Goal: Report actual worker and device state rather than only whether the parent service is running.

Deliverables:

- Define a minimal parent/worker readiness and error channel.
- Distinguish waiting for device, opening, grabbed/listening, backing off, invalid configuration,
  and shutting down.
- Add `macropad status` with device, profile paths, worker state, PID, matched event paths, failure
  reason, and next retry where available.
- Ensure "listening" means the worker actually grabbed the input path, not merely that a matching
  device was visible before child startup.
- Keep the control/status mechanism local to the user and avoid creating a general remote API.

Acceptance criteria:

- The status command identifies a failed worker while healthy workers remain clearly healthy.
- Permission and grab failures are visible without searching raw tracebacks.
- The daemon still works headlessly when no status client is connected.

Verification:

- Add worker/supervisor state-transition tests and service lifecycle coverage.
- Update the runtime architecture documentation and Mermaid diagrams.
- Run all standard checks plus `make test-service` and `make test-systemd`.

### 9. Improve Installation, XDG, And Service Lifecycle UX

Status: [x] Complete

Goal: Support normal user installation without requiring a development checkout.

Deliverables:

- Document a released `uv tool` or `pipx` installation path separately from development setup.
- Respect `XDG_CONFIG_HOME`, with a deliberate compatibility story for existing `~/.config`
  profiles.
- Provide install, enable/start, status, logs, restart, stop, disable, and uninstall service flows.
- Make the installed service invoke the installed executable; retain checkout rendering only as a
  documented development path.
- Add `--version` and either document shell completion activation or remove unused completion
  machinery.
- Clearly document native build dependencies and input permission setup.

Acceptance criteria:

- A user can install, initialize, enable, inspect, and uninstall Macropad using documented commands.
- Service installation is path-safe and does not depend on the repository remaining in place.
- Existing default-path users do not silently lose access to their profiles.

Verification:

- Extend wheel, service, systemd, and distribution smoke tests.
- Run `uv lock --check`, `make test-wheel`, `make test-service`, `make test-systemd`, and `make build`
  in addition to standard checks.

### 10. Make Notifications Truly Optional

Status: [x] Complete

Goal: Avoid requiring DBus development packages for users who do not need desktop notifications.

Deliverables:

- Move notification dependencies to an optional package extra if packaging behavior permits it.
- Lazy-load the notification backend and keep the daemon fully functional when it is absent.
- Remember a failed initialization and avoid retrying on every layer event.
- Define a low-noise global notification preference without putting operating-system concerns into
  individual profile fragments.
- Keep configuration reload failures visible through logs even when notifications are disabled.

Acceptance criteria:

- A headless installation without DBus Python bindings can listen and execute actions.
- Installing the notification extra enables existing desktop behavior.
- Missing or failed notifications do not produce repeated warnings.

Verification:

- Test package installation both with and without the optional extra.
- Run all standard and wheel checks.

### 11. Make Event Timing Understandable And Configurable

Status: [ ] Not started

Goal: Make tap, multi-tap, hold, and one-shot behavior consistent across keyboards and user
preferences.

Deliverables:

- Define profile-level timing fields for multi-tap resolution and one-shot layer timeout.
- Decide whether hold remains based on kernel repeat events or becomes duration-based; document and
  test the chosen semantics.
- Preserve current values as defaults for version 1 profiles unless usability testing supports a
  deliberate versioned change.
- Validate bounds and report timing paths in profile diagnostics.
- Document the responsiveness tradeoff introduced by delayed multi-tap resolution.

Acceptance criteria:

- Timing behavior is monotonic, threadless, deterministic, and covered with fake-clock tests.
- Existing profiles retain their current behavior by default.
- Invalid timing values fail before workers are reconciled.

Verification:

- Extend profile and handler tests without real sleeps.
- Run `make format`, `make lint`, and `make test`.

### 12. Improve Layer Semantics

Status: [ ] Not started

Goal: Support common macropad layer workflows without duplicated bindings or fragile command
combinations.

Deliverables:

- Evaluate and specify base-binding fallback for keys absent from an active layer.
- Add first-class momentary and toggle layer behavior if user scenarios require them.
- Keep persistent and one-shot behavior compatible unless a profile version change is justified.
- Define notification behavior for rapid layer transitions.
- Add examples that demonstrate activation, fallback, cancellation, and timeout behavior.

Acceptance criteria:

- Layer behavior is explicit in the profile schema and does not depend on undocumented binding
  duplication.
- One-shot, persistent, momentary, and toggle transitions cannot leave stale delayed events.
- Existing layer tests continue to pass or have a documented migration path.

Verification:

- Add a state-transition test matrix using fake clocks.
- Run `make format`, `make lint`, and `make test`.

### 13. Add Native Keyboard Shortcut And Chord Actions

Status: [ ] Not started

Goal: Let users emit common shortcuts without depending on desktop-specific shell tools.

Deliverables:

- Research a Linux input-output backend that behaves acceptably under both X11 and Wayland.
- Define typed profile actions for key presses, chords, and sequences while preserving trusted shell
  strings as the simple existing action form.
- Include explicit key-down/key-up cleanup so failures cannot leave virtual modifiers held.
- Document permissions and security implications of virtual input creation.
- Keep this feature separate from physical device selection.

Acceptance criteria:

- Common shortcuts such as Ctrl+C and media keys can be expressed without shell quoting.
- Interrupted or failed sequences release all virtual keys.
- Existing shell-only profiles remain valid.

Verification:

- Add unit tests for sequence generation and cleanup.
- Add an opt-in uinput integration test where CI permissions allow it.
- Update architecture documentation for the new operating-system adapter.

## Deferred Until Concrete Demand

### 14. Structured Hardware Selectors

Status: [ ] Deferred

Consider vendor/product IDs, physical path, or serial selectors only after real name-collision cases
show that warnings and path visibility are insufficient. Any design must preserve multi-node device
support and define hot-plug identity carefully.

### 15. Graphical Profile Editor

Status: [ ] Deferred

Build a GUI only after `validate`, `doctor`, `monitor`, `init`, and `status` provide stable product
APIs and profile semantics. A GUI should consume those capabilities rather than reimplement runtime
logic.

## Completion Definition

The roadmap is complete when a new Linux user can install Macropad, verify permissions, identify a
device and key, create and validate a profile, safely test it, run it as a service, diagnose failures,
and remove the installation using documented commands, before any optional advanced macro features
are required.
