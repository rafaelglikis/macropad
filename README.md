# Macropad

[![CI](https://github.com/rafaelglikis/macropad/actions/workflows/ci.yml/badge.svg)](https://github.com/rafaelglikis/macropad/actions/workflows/ci.yml)

Turn every keyboard into a macropad.

Macropad currently supports Linux only. macOS and Windows support are coming soon.

## Install

Install the compiler and Python headers required to build the Linux input dependency:

Debian/Ubuntu:

```bash
sudo apt install build-essential python3-dev
```

Fedora:

```bash
sudo dnf install gcc python3-devel
```

The distribution is named `poor-mans-macropad`; the installed command remains `macropad`. Install it
in an isolated environment with either `pipx` or
[`uv`](https://docs.astral.sh/uv/getting-started/installation/) rather than modifying the system
Python.

### pipx

Install `pipx` from the distribution:

```bash
sudo apt install pipx
```

On Fedora, use:

```bash
sudo dnf install pipx
```

Then ensure its command directory is on `PATH` and install Macropad:

```bash
pipx ensurepath
pipx install poor-mans-macropad
```

To include desktop notifications, install `poor-mans-macropad[notifications]` instead.

Start a new login shell after the first `pipx ensurepath` if `macropad` is not immediately found.

### uv

If `uv` is already installed, its tool interface provides the same isolated installation:

```bash
uv tool install poor-mans-macropad
```

To include desktop notifications, install `poor-mans-macropad[notifications]` instead.

### Optional Desktop Notifications

Desktop notifications are optional. The base installation listens for input, reloads profiles, and
executes actions without importing DBus. To install the notification extra, first install its native
build dependencies.

Debian/Ubuntu:

```bash
sudo apt install pkg-config libdbus-1-dev libglib2.0-dev
```

Fedora:

```bash
sudo dnf install pkgconf-pkg-config dbus-devel glib2-devel
```

Then use one of these package specifications with the installer chosen above:

```bash
pipx install 'poor-mans-macropad[notifications]'
uv tool install 'poor-mans-macropad[notifications]'
```

The notification dependencies are installed only when the `notifications` extra is explicitly
requested. A base `pipx install poor-mans-macropad` or `uv tool install poor-mans-macropad`
intentionally omits `dbus-python` and `notify2`. The native headers above must be present while
installing the extra.

At runtime, notifications also require a graphical session, a working DBus session, and an available
desktop notification service. Check all installation and runtime conditions with:

```bash
macropad doctor
```

Without the extra, an attempted notification produces one warning and the process continues without
further attempts. Disable notification attempts explicitly in the foreground with:

```bash
macropad --no-notifications listen
```

Confirm the installed version:

```bash
macropad --version
```

### Input Permissions

Run `macropad doctor` first. If it reports input-device permission failures, add the current user to
the `input` group, then log out and back in:

```bash
sudo usermod --append --groups input "$USER"
```

This command applies to Debian, Ubuntu, and Fedora. Some desktop environments already provide access
through per-session ACLs, so group membership is unnecessary when `macropad doctor` reports input
access as `PASS`. Membership in the `input` group grants access to all input events and can expose
every keystroke, including passwords. Prefer a device-specific udev rule when broad input access is
not acceptable.

## Update

Upgrade Macropad with the installer that owns it:

```bash
pipx upgrade poor-mans-macropad
```

or:

```bash
uv tool upgrade poor-mans-macropad
```

Then refresh the generated service path, restart the service, and confirm the installed version:

```bash
macropad service install
macropad service restart
macropad --version
```

## Usage

Listen using profiles from the default configuration directory:

```bash
macropad listen
macropad --verbose listen
macropad --debug listen
```

Validate profiles without opening or grabbing input devices:

```bash
macropad validate
macropad validate profile.yml
macropad validate --directory ./profiles
```

Check input permissions, profile access, and the runtime environment:

```bash
macropad doctor
```

Inspect live keyboard worker and device state:

```bash
macropad status
```

Create a first profile through guided device and key detection:

```bash
macropad init
```

List readable input devices and stream key names without grabbing the keyboard:

```bash
macropad monitor
macropad monitor 'Exact Device Name'
```

## Profile Format

Macropad loads `.yml` files from `$XDG_CONFIG_HOME/macropad/profiles/`, defaulting to
`~/.config/macropad/profiles/` when `XDG_CONFIG_HOME` is unset or relative. A profile uses the strict
version 1 format and names a keyboard exactly as Linux evdev reports it:

When a custom absolute `XDG_CONFIG_HOME` is configured but its Macropad profile directory does not
exist, an existing legacy `~/.config/macropad/profiles/` directory remains active. Create or migrate
profiles into the XDG directory to switch; when both directories exist, the XDG directory wins.
Macropad never moves profile files automatically.

```yaml
device: My Macro Keyboard
version: '1'
bindings:
  KEY_A: notify-send Macropad 'A released'
  KEY_B:
    down: playerctl play-pause
    up:
      - notify-send Macropad 'B released'
      - logger 'Macropad B released'
```

Unknown top-level fields, context fields, key names, event names, layer fields, and duplicate YAML
keys are errors. `device` must be a non-empty string. `version` may be the string `'1'` or integer
`1`; omitted versions default to 1. A complete merged device configuration must contain at least one
base action.

Use any key name exported by Linux evdev, such as `KEY_A`, `KEY_UP`, or `KEY_PLAYPAUSE`. A command
string is shorthand for an `up` action. An event can run one command string or a non-empty list of
commands, which are submitted in the listed order as independent detached processes.

### Events

| Event        | Behavior                                                                                         |
|--------------|--------------------------------------------------------------------------------------------------|
| `down`       | Runs on key press. A binding containing only `down` also repeats on kernel key-repeat events.    |
| `up`         | Runs when the key is released.                                                                   |
| `hold`       | Resolves when evdev reports that the key was held; this depends on the keyboard repeat behavior. |
| `double_tap` | Runs after two press/release pairs occur within the multi-tap resolution window.                 |
| `triple_tap` | Runs after three press/release pairs occur within the multi-tap resolution window.               |

Bindings with multiple event choices or requiring hold or multi-tap resolution wait for a 200 ms
quiet period. Simple bindings containing one immediate event run without that delay.

```yaml
device: My Macro Keyboard
version: '1'
bindings:
  KEY_C:
    up: notify-send Macropad 'Single tap'
    double_tap: notify-send Macropad 'Double tap'
    triple_tap: notify-send Macropad 'Triple tap'
  KEY_D:
    up: notify-send Macropad 'Released normally'
    hold: notify-send Macropad 'Held and released'
```

### Timing

Timing configuration is optional. Profiles without it retain the existing 200 ms multi-tap window
and five-second one-shot timeout. Configure either or both fields at the top level:

```yaml
device: My Macro Keyboard
version: '1'
timing:
  multi_tap_ms: 300
  one_shot_timeout_ms: 8000
bindings:
  KEY_C:
    up: notify-send Macropad 'Single tap'
    double_tap: notify-send Macropad 'Double tap'
  KEY_N:
    up: ^layer navigation once
layers:
  navigation:
    bindings:
      KEY_H: notify-send Macropad Left
```

| Field                 | Range          | Default  | Behavior                                                                                                  |
|-----------------------|----------------|----------|-----------------------------------------------------------------------------------------------------------|
| `multi_tap_ms`        | 1–5,000 ms     | 200 ms   | Quiet period after the latest event before a binding that needs hold or multi-tap resolution is resolved. |
| `one_shot_timeout_ms` | 1–3,600,000 ms | 5,000 ms | Idle time a one-shot layer waits for its next key before deactivating.                                    |

Increasing `multi_tap_ms` gives slower taps more time to form double- or triple-tap sequences, but
also delays single-tap and hold resolution for bindings that contain those event choices. Hold
detection itself remains based on evdev kernel-repeat events, so this setting does not turn hold into
a duration-based action. One-shot timing is cancelled once a key claims the layer; that key completes
normally and then deactivates the layer.

### Application Context

An optional context command can select a layer from the command's output when a key is pressed. This
supports desktop-specific active-window tools without coupling Macropad to one desktop environment:

```yaml
device: My Macro Keyboard
version: '1'
context:
  command: kdotool getactivewindow getwindowclassname
  layers:
    org.kde.konsole: terminal
    jetbrains-phpstorm: editor
bindings:
  KEY_F1: notify-send Macropad Base
layers:
  terminal:
    bindings:
      KEY_F1: notify-send Macropad Terminal
  editor:
    bindings:
      KEY_F1: notify-send Macropad Editor
```

The command is a trusted shell string, like an action. Its trimmed standard output must exactly match
a key under `context.layers`; unknown or empty output uses normal bindings. Macropad waits at most
100 ms for the command. Start failures, timeouts, and nonzero exit statuses are logged and fall back
to normal bindings rather than blocking input indefinitely.

Context is resolved only for the initial key press and remains attached through repeats and release,
so an action that changes focus cannot change the matching release action. A manually activated
layer has priority, followed by the context layer and then base bindings. Each layer's `fallback`
setting still controls whether lookup continues. Context mappings may reference layers from another
profile fragment; fragments must use the same command, and conflicting mappings are rejected.

### Layers

Layer commands begin with `^` and are handled by Macropad instead of the shell:

| Command                   | Behavior                                                                       |
|---------------------------|--------------------------------------------------------------------------------|
| `^layer <name>`           | Activates a persistent layer.                                                  |
| `^layer <name> once`      | Activates a layer for the next key, with a configurable idle timeout.         |
| `^layer <name> momentary` | Activates a layer while its activation key is held, then restores the prior layer. |
| `^layer <name> toggle`    | Toggles a layer on or off. Its activation key always remains an escape.       |
| `^default_layer`          | Deactivates the current layer.                                                 |

Layer references are checked after all fragments for a device are merged. This permits one fragment
to activate a layer defined in another fragment while still rejecting genuinely missing layers.
By default, a key absent from the active layer uses its base binding. A layer binding overrides the
base binding for that key. This changes the earlier version 1 behavior, which ignored missing layer
keys; add `fallback: none` to preserve that behavior for a layer. A fallback binding consumes a
one-shot layer just like a binding declared directly in that layer.

Top-level layers collect all alternate bindings in one section:

```yaml
device: My Macro Keyboard
version: '1'
bindings:
  KEY_SPACE:
    up: ^layer navigation
  KEY_N:
    up: ^layer navigation once
  KEY_M:
    down: ^layer navigation momentary
  KEY_T: ^layer navigation toggle
layers:
  navigation:
    fallback: base
    bindings:
      KEY_H: notify-send Macropad Left
      KEY_L: notify-send Macropad Right
      KEY_ESC: ^default_layer
```

Momentary commands are valid only in a binding whose sole event is `down`; multiple commands may
still be listed under that event. Releasing the activation key restores the layer that was active
before it was held. A later persistent, one-shot, or toggle transition supersedes that restoration.
Momentary press/release transitions are omitted from desktop notifications to avoid noise. Other
layer modes retain activation and deactivation notifications.

Layer metadata can be declared without top-level bindings when the bindings live inline:

```yaml
layers:
  navigation:
    fallback: none
```

An inline layer defines the alternate action beside a key's base action. It produces the same layer
configuration as the top-level form:

```yaml
device: My Macro Keyboard
version: '1'
bindings:
  KEY_SPACE:
    up: ^layer navigation
  KEY_H:
    up: notify-send Macropad Base
    layers:
      navigation: notify-send Macropad Left
```

An inline command string is shorthand for `up`, matching base and top-level layer bindings. Use an
explicit event mapping when an inline layer binding runs multiple commands.

Layers cannot contain nested layers. Persistent layers remain active until replaced or an action
runs `^default_layer`. Toggle layers deactivate when their activation key is pressed again, including
when `fallback: none` would otherwise block that key. One-shot layers deactivate after the claimed
key is released or the idle timeout passes.

### Profile Fragments

Multiple files with the same exact `device` name are merged before a worker starts. This allows base
bindings and layers to be organized into separate files:

```yaml
# media.yml
device: My Macro Keyboard
version: '1'
bindings:
  KEY_PLAYPAUSE: playerctl play-pause
```

```yaml
# volume.yml
device: My Macro Keyboard
version: '1'
bindings:
  KEY_VOLUMEUP: playerctl volume 0.05+
  KEY_VOLUMEDOWN: playerctl volume 0.05-
```

Bindings for different keys or events combine. Defining different commands for the same device,
layer, key, and event is a conflict and validation fails with the later file and field path.
Timing fields can also be split across fragments. Repeating the same value is allowed; different
values for the same timing field are a conflict attributed to the later fragment.

When default profiles or `--watch` directories are used, Macropad recognizes `.yml` files that are
created, modified, deleted, or moved. Move events inspect both source and destination paths so
editors that atomically replace profiles through temporary files are supported. A burst of changes
is coalesced until the directory has been quiet for one second, then the complete candidate set is
loaded and merged once. An invalid edit is reported while the last valid workers continue running.

### Action Execution And Security

Profile actions are trusted shell code and must never be loaded from an untrusted source. Each
command runs with `shell=True`, starts from `/`, inherits the Macropad process environment, receives
no stdin, and normally has stdout and stderr discarded. Actions are detached and continue across
profile reloads or worker shutdown.

Each keyboard worker tracks at most eight concurrent actions. Additional actions are dropped rather
than queued until an earlier action exits. The systemd user service includes `~/bin`, `~/.local/bin`,
and standard system command directories in its deterministic `PATH`. Use absolute paths or a service
override for commands installed in other interactive-shell or tool-manager directories.

### Runtime And Action Debugging

Global logging options precede the subcommand and work with both `macropad` and
`python -m macropad`:

```bash
macropad --verbose listen
python -m macropad --debug listen
macropad --action-debug listen
```

Normal mode shows warnings and errors, including failed action starts, nonzero exits, worker
failures, and actions dropped at the concurrency limit. `--verbose` adds lifecycle summaries,
resolved action submissions, process starts, successful exits, layer transitions, and profile
reloads. `--debug` also shows unbound input, event resolution, active binding selection, and the
action execution environment.

Action diagnostics identify the resolved device, `KEY_*` name, event, base or named layer, command,
process ID, exit status, and concurrency count where applicable. Debug environment output includes
the `/` working directory, action `PATH`, display names, whether a DBus session address is set, and
whether output is discarded or inherited. It intentionally does not dump the complete environment
or the DBus address.

`--action-debug` implies debug logging and changes only action stdout and stderr: they inherit the
Macropad process streams instead of `/dev/null`. In a foreground listener they appear in that
terminal; when configured on the systemd service command they go to the journal. This output can
contain credentials or other sensitive application data, so enable it only while diagnosing a
trusted action. Stdin remains `/dev/null`, actions remain detached, and the eight-action limit is
unchanged.

The generated service uses `--verbose` so lifecycle and action summaries remain available through
`macropad service logs`. To capture action output in the journal, add `--action-debug` before
`listen` in the service's effective `ExecStart`, reload the unit, and restart the service. Remove it
after debugging.

### Validation

`macropad validate` uses the same loading, strict schema validation, fragment grouping, merge
conflict detection, and merged semantic checks as startup. It does not initialize notifications,
start workers, execute actions, or open input devices.

With no arguments, it validates the default profile directory without creating it. Explicit files
and directories can be combined:

```bash
macropad validate base.yml --directory ./profile-fragments
```

A valid complete set prints a blank-separated `PASS` section for each file, followed by the
profile-file and device counts, and exits with status 0. Missing or invalid files get their own
`FAIL` sections with multiline source and field-path diagnostics. Files that pass standalone schema
validation show `PARSED` instead of `PASS` when merged validation cannot complete. Unresolved layers
and conflicts are attributed to the relevant file; device-wide errors use a `Profile set` section.

## Diagnostics

Run `macropad doctor` before starting the service to check input-device enumeration, open and
exclusive-grab access, the default profile directory, optional desktop notifications, executable and
service paths, current and service action `PATH` values, and graphical-session variables. Each
blocking `FAIL` includes remediation.
Expected grabs held by an active Macropad service are reported as nonblocking `WARN` results;
optional notification, service, and session-environment gaps are `INFO` results.

The input check briefly grabs and immediately releases each readable event device, closing every
handle even when a check fails. When the service is active, stop it and rerun doctor only when you
need to distinguish Macropad's expected grabs from another input grabber:

```bash
macropad service stop
macropad doctor
macropad service start
```

## Device Monitoring

Run `macropad monitor` without arguments to list every readable input device. Devices sharing an
exact evdev name are grouped together and every matching `/dev/input/event*` path is shown; paths
that cannot be opened include their permission or device error. Device names matching a profile in
the default profile directory are marked `[configured]`.

Pass an exact listed name to stream key activity:

```text
CONNECTED    /dev/input/event12
down         KEY_A                    /dev/input/event12
repeat       KEY_A                    /dev/input/event12
up           KEY_A                    /dev/input/event12
```

Monitoring never exclusively grabs a device, so normal keyboard input continues. It opens every
current path with the selected name, reports disconnects, reacquires matching paths after reconnect,
and exits cleanly with Ctrl+C or SIGTERM. An active Macropad worker already holds its configured
device exclusively; if monitor connects but shows no events, run `macropad service stop` before
monitoring and start the service again afterward.

## Guided Initialization

Run `macropad init` to create one working release binding without manually discovering evdev names
or writing YAML. The command first runs the blocking input-device checks from `macropad doctor`, then
asks you to disconnect the target keyboard. Detection starts only after you confirm that it is
disconnected: reconnect it and press the key you want to configure. By default, each device or key
capture times out after 60 seconds; use `--timeout SECONDS` to choose another positive timeout.

The command asks for a trusted shell command and writes a new fragment under the resolved default
profile directory. Generated macros run when the captured key is released. The directory follows the
same XDG and legacy fallback rules as `listen` and `validate`.

If the detected device already has profiles, `init` lists every existing fragment and asks whether to
add a new one. It never edits those files. If the captured key already has an `up` action, release the
key and capture another one or cancel. Other events on that key can safely merge with the generated
release binding.

Filenames are derived from the device and key, for example
`macro_keyboard_key_a.yml`. Existing filenames are preserved and a numeric suffix is selected. The
new fragment is conflict-checked against the complete existing profile set before creation, opened
exclusively, and validated with the normal complete on-disk validation workflow before success is
reported. Cancellation, timeout, write failure, or validation failure removes the new file without
touching existing fragments.

An active Macropad service may already own a configured keyboard and prevent non-grabbing key
capture. If initialization times out for an existing device, stop the service and retry:

```bash
macropad service stop
macropad init
```

On success, `init` reports the exact path and refreshes the systemd service state. Active state alone
cannot prove which arguments a customized service uses, so automatic loading is confirmed only as a
condition of the standard `listen --watch` command and default profile directory. If the service is
inactive, start in the foreground with `macropad listen` or use the service command shown by `init`.

## Runtime Status

`macropad status` reports whether each configured keyboard worker is actually waiting, opening event
paths, listening after a successful exclusive grab, backing off after failure, reporting an input
error, or shutting down. It includes the parent and worker PIDs, profile fragment paths, currently
grabbed event paths, failure reason, and retry delay where available:

```text
Macropad parent PID: 1234

Macro Keyboard
  state: listening
  pid: 1235
  profiles: /home/user/.config/macropad/profiles/macro.yml
  paths: /dev/input/event12

Media Pad
  state: backing_off (retry in 4.0s)
  profiles: /home/user/.config/macropad/profiles/media.yml
  error: process 1236 exited
```

An invalid watched profile candidate is shown separately while the last valid workers keep running.
Permission and grab errors include the affected event path when known. `listening` is reported only
after the worker successfully grabs at least one matching path; a visible device before child startup
does not count as listening.

The command connects to a read-only Unix socket owned by the listening parent under
`$XDG_RUNTIME_DIR/macropad/`, with a user-specific directory under the system temporary directory as
a fallback. The directory and socket are user-only, stale sockets are removed safely, and no remote
control operations are exposed. If no parent is reachable, the command reports whether the systemd
service is active and points to the appropriate next command.

`macropad status` and `macropad service status` answer different questions: the former reports live
Macropad worker/device readiness, while the latter remains a direct proxy for systemd unit state and
logs.

## Service

Install and start the systemd user service:

```bash
macropad service install
```

To persistently disable notification attempts in the generated service, install it with:

```bash
macropad --no-notifications service install
```

The command writes `$XDG_CONFIG_HOME/systemd/user/macropad.service` when `XDG_CONFIG_HOME` is
absolute, defaulting to `~/.config/systemd/user/macropad.service`, then reloads systemd and enables
and starts the unit. The generated unit invokes the `macropad` executable from the active tool
environment and does not depend on a source checkout. Reinstalling updates a recognized generated
unit. Macropad refuses to replace an unrelated unit at that path unless
`macropad service install --force` is used.

The generated unit starts as part of the standard systemd graphical session, after the desktop has
published variables such as `DISPLAY`, `WAYLAND_DISPLAY`, and `XAUTHORITY`. It stops with that
session and remains desktop-environment independent.

By default, profile actions use a deterministic `PATH` containing standard system and user command
directories. To capture the current shell's `PATH` in the generated unit instead, run:

```bash
macropad service install --action-path "$PATH"
```

The value is persisted until the next service installation. Every entry must be non-empty and
absolute; duplicate entries are removed. Review the value first because profile actions resolve
commands through these directories with your user permissions.

Manage the installed unit through the CLI:

```bash
macropad service status
macropad service logs
macropad service restart
macropad service stop
macropad service disable
```

`service logs` follows the systemd journal until interrupted. These commands preserve the output and
exit status from `systemctl --user` or `journalctl --user`. Use `macropad listen` instead when running
Macropad directly in the foreground.

### Uninstall

Remove the service before uninstalling the tool:

```bash
macropad service uninstall
uv tool uninstall poor-mans-macropad
```

For a `pipx` installation, replace the final command with:

```bash
pipx uninstall poor-mans-macropad
```

`service uninstall` stops and disables the unit, removes it only when its generated marker is
present, and reloads systemd. It does not remove profiles.

## Coming Up Next

- **Native Keyboard Shortcuts And Chords:** Emit key presses, shortcuts, and sequences without
  depending on external tools such as `ydotool` or `xdotool`.
- **Tray Icon:** Inspect service status, reload profiles, and access common controls from the desktop.
- **Context-Aware Bindings:** Change bindings based on the current application, window title, or
  other context.
- **Windows And macOS Compatibility:** Bring Macropad profiles and workflows to additional desktop
  platforms.

## Changelog

See the [changelog](https://github.com/rafaelglikis/macropad/blob/main/CHANGELOG.md) for released and
upcoming user-facing changes.

## Development

Install the base and optional-notification native dependencies listed above before running the full
integration suite, then create the project environment. Development uses the same service renderer
and lifecycle as released installations:

```bash
make
make install-editable
uv run macropad service install
```

```bash
make test
make test-init
make test-wheel
make test-service
make test-systemd
make lint
make build
```

Run `make format` to apply the Ruff lint and formatting policy.

CI runs the unit suite on Python 3.10 through 3.14, verifies linting, formatting, the lockfile, wheel
installation, packaged assets, service lifecycle, systemd unit, and distribution build. See
[`RELEASING.md`](RELEASING.md) for the Trusted Publishing release process.

## License

Macropad is available under the [MIT License](LICENSE).
