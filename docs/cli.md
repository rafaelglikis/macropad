# Commands

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
same [XDG and legacy fallback rules](profiles.md) as `listen` and `validate`.

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

## Runtime And Action Debugging

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
