# Macropad

[![CI](https://github.com/rafaelglikis/macropad/actions/workflows/ci.yml/badge.svg)](https://github.com/rafaelglikis/macropad/actions/workflows/ci.yml)

Turn every keyboard into a macropad.

## Install

Install the system dependencies required to build the Python DBus bindings:

Debian/Ubuntu:

```bash
sudo apt install libdbus-1-dev libglib2.0-dev
```

Fedora:

```bash
sudo dnf install dbus-devel glib2-devel
```

Then install the Python dependencies:

```bash
make
```

Install `macropad` as a user-level editable command when developing locally:

```bash
make install-editable
```

## Usage

Listen using profiles from the default configuration directory:

```bash
uv run macropad listen
```

Detect a newly connected keyboard and generate a profile:

```bash
uv run macropad detect --generate-profile
```

Validate profiles without opening or grabbing input devices:

```bash
uv run macropad validate
uv run macropad validate profile.yml
uv run macropad validate --directory ./profiles
```

The module entry point is also available:

```bash
uv run python -m macropad --help
```

## Profile Format

Macropad loads `.yml` files from `~/.config/macropad/profiles/` by default. A profile uses the
strict version 1 format and names a keyboard exactly as Linux evdev reports it:

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

Unknown top-level fields, key names, event names, layer fields, and duplicate YAML keys are errors.
`device` must be a non-empty string. `version` may be the string `'1'` or integer `1`; omitted
versions default to 1. A complete merged device configuration must contain at least one base action.

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

### Layers

Layer commands begin with `^` and are handled by Macropad instead of the shell:

| Command              | Behavior                                                             |
|----------------------|----------------------------------------------------------------------|
| `^layer <name>`      | Activates a persistent layer.                                        |
| `^layer <name> once` | Activates a layer for the next key, with a five-second idle timeout. |
| `^default_layer`     | Deactivates the current layer.                                       |

Layer references are checked after all fragments for a device are merged. This permits one fragment
to activate a layer defined in another fragment while still rejecting genuinely missing layers.
Active layers use only their own bindings; keys absent from the layer do not fall back to base
bindings.

Top-level layers collect all alternate bindings in one section:

```yaml
device: My Macro Keyboard
version: '1'
bindings:
  KEY_SPACE:
    up: ^layer navigation
  KEY_N:
    up: ^layer navigation once
layers:
  navigation:
    bindings:
      KEY_H: notify-send Macropad Left
      KEY_L: notify-send Macropad Right
      KEY_ESC: ^default_layer
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
      navigation:
        up: notify-send Macropad Left
```

Layers cannot contain nested layers. Persistent layers remain active until an action runs
`^default_layer`. One-shot layers deactivate after the claimed key is released or the idle timeout
passes.

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

When default profiles or `--watch` directories are used, Macropad recognizes `.yml` files that are
created, modified, deleted, or moved. Move events inspect both source and destination paths so
editors that atomically replace profiles through temporary files are supported. A burst of changes
is coalesced until the directory has been quiet for one second, then the complete candidate set is
loaded and merged once. An invalid edit is reported while the last valid workers continue running.

### Action Execution And Security

Profile actions are trusted shell code and must never be loaded from an untrusted source. Each
command runs with `shell=True`, starts from `/`, inherits the Macropad process environment, receives
no stdin, and has stdout and stderr discarded. Actions are detached and continue across profile
reloads or worker shutdown.

Each keyboard worker tracks at most eight concurrent actions. Additional actions are dropped rather
than queued until an earlier action exits. The systemd user service includes `~/bin`, `~/.local/bin`,
and standard system command directories in its deterministic `PATH`. Use absolute paths or a service
override for commands installed in other interactive-shell or tool-manager directories.

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

## Service

Install and start the systemd user service:

```bash
make systemd
uv run macropad service enable
uv run macropad service start
```

`make systemd` renders the checked-in unit template for the current checkout and validates it before installation.

Manage the installed unit through the CLI:

```bash
uv run macropad service status
uv run macropad service logs
uv run macropad service restart
uv run macropad service stop
uv run macropad service disable
```

`service logs` follows the systemd journal until interrupted. These commands preserve the output and
exit status from `systemctl --user` or `journalctl --user`. Use `macropad listen` instead when running
Macropad directly in the foreground.

## Development

```bash
make test
make test-wheel
make test-service
make test-systemd
make lint
make build
```

Run `make format` to apply the Ruff lint and formatting policy.

CI runs the unit suite on Python 3.10 through 3.14, verifies linting, formatting, the lockfile, wheel installation, packaged assets, service lifecycle, systemd unit, and distribution build.

## License

Macropad is available under the [MIT License](LICENSE).
