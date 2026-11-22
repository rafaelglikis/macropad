# Profile Format

Macropad loads `.yml` files from `$XDG_CONFIG_HOME/macropad/profiles/`, defaulting to
`~/.config/macropad/profiles/` when `XDG_CONFIG_HOME` is unset or relative. A profile uses the strict
version 1 format and names a keyboard exactly as Linux evdev reports it:

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

When a custom absolute `XDG_CONFIG_HOME` is configured but its Macropad profile directory does not
exist, an existing legacy `~/.config/macropad/profiles/` directory remains active. Create or migrate
profiles into the XDG directory to switch; when both directories exist, the XDG directory wins.
Macropad never moves profile files automatically.

Unknown top-level fields, context fields, key names, event names, layer fields, and duplicate YAML
keys are errors. `device` must be a non-empty string. `version` may be the string `'1'` or integer
`1`; omitted versions default to 1. A complete merged device configuration must contain at least one
base action.

Use any key name exported by Linux evdev, such as `KEY_A`, `KEY_UP`, or `KEY_PLAYPAUSE`. A command
string is shorthand for an `up` action. An event can run one command string or a non-empty list of
commands, which are submitted in the listed order as independent detached processes. See
[Action Execution And Security](security.md) for how Macropad runs them.

## Events

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

## Timing

Timing configuration is optional. Profiles without it use a 200 ms multi-tap window and a five-second one-shot timeout.
Configure either or both fields at the top level:

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

## Application Context

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

The command is a trusted shell string, like an [action](security.md). Its trimmed standard output must exactly match
a key under `context.layers`; unknown or empty output uses normal bindings. Macropad waits at most
100 ms for the command. Start failures, timeouts, and nonzero exit statuses are logged and fall back
to normal bindings rather than blocking input indefinitely.

Context is resolved only for the initial key press and remains attached through repeats and release,
so an action that changes focus cannot change the matching release action. A manually activated
layer has priority, followed by the context layer and then base bindings. Each layer's `fallback`
setting still controls whether lookup continues. Context mappings may reference layers from another
profile fragment; fragments must use the same command, and conflicting mappings are rejected.

## Layers

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
base binding for that key. Add `fallback: none` to make a layer ignore keys it does not bind. A fallback binding
consumes a one-shot layer just like a binding declared directly in that layer.

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

## Profile Fragments

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

## Validation

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
