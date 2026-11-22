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
Python:

```bash
pipx install poor-mans-macropad
```

or:

```bash
uv tool install poor-mans-macropad
```

The [install guide][install] covers installing `pipx`, optional desktop notifications, input permissions, and updating.

## Quickstart

Check input permissions and the runtime environment:

```bash
macropad doctor
```

Create a first profile through guided device and key detection:

```bash
macropad init
```

Install and start the systemd user service, which loads profiles from the default configuration directory and reloads
them when they change:

```bash
macropad service install
```

Run `macropad listen` instead to stay in the foreground. The [commands][commands] page lists every command.

## Profile Format

Profiles are `.yml` files in `$XDG_CONFIG_HOME/macropad/profiles/`, defaulting to `~/.config/macropad/profiles/`. Each
one names a keyboard exactly as Linux evdev reports it and maps keys to shell commands:

```yaml
device: My Macro Keyboard
version: '1'
bindings:
  KEY_A: notify-send Macropad 'A released'
  KEY_B:
    down: playerctl play-pause
```

Profile actions are trusted shell code, so never load a profile from an untrusted source. The
[profile reference][profiles] has the complete format.

## Documentation

The [documentation][docs] covers [installation][install], [profiles][profiles], [commands][commands], the
[service][service], [action execution and security][security], and the [architecture][architecture].

## Coming Up Next

- **Native Keyboard Shortcuts And Chords:** Emit key presses, shortcuts, and sequences without
  depending on external tools such as `ydotool` or `xdotool`.
- **Tray Icon:** Inspect service status, reload profiles, and access common controls from the desktop.
- **Windows And macOS Compatibility:** Bring Macropad profiles and workflows to additional desktop
  platforms.

## Changelog

See the [changelog](https://github.com/rafaelglikis/macropad/blob/main/CHANGELOG.md) for released and
upcoming user-facing changes.

## Development

Install the base and optional-notification native dependencies from the [install guide][install] before running the
full integration suite, then create the project environment. Development uses the same service renderer
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
[`RELEASING.md`][releasing] for the Trusted Publishing release process.

## License

Macropad is available under the [MIT License][license].

[docs]: https://github.com/rafaelglikis/macropad/blob/main/docs/README.md
[install]: https://github.com/rafaelglikis/macropad/blob/main/docs/install.md
[profiles]: https://github.com/rafaelglikis/macropad/blob/main/docs/profiles.md
[commands]: https://github.com/rafaelglikis/macropad/blob/main/docs/cli.md
[service]: https://github.com/rafaelglikis/macropad/blob/main/docs/service.md
[security]: https://github.com/rafaelglikis/macropad/blob/main/docs/security.md
[architecture]: https://github.com/rafaelglikis/macropad/blob/main/docs/architecture.md
[releasing]: https://github.com/rafaelglikis/macropad/blob/main/RELEASING.md
[license]: https://github.com/rafaelglikis/macropad/blob/main/LICENSE
