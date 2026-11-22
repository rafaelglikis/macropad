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

- [Profiles][profiles] covers events, timing, application context, layers, fragments, and validation.
- [Commands][commands] covers `doctor`, `monitor`, `init`, `status`, and logging options.
- [Service][service] covers the systemd user service and uninstalling.
- [Action execution and security][security] explains how Macropad runs profile actions.
- [Architecture][architecture] describes modules, processes, and runtime flows for contributors.

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
[`RELEASING.md`][releasing] for the Trusted Publishing release process.

## License

Macropad is available under the [MIT License][license].

[profiles]: https://github.com/rafaelglikis/macropad/blob/main/docs/profiles.md
[commands]: https://github.com/rafaelglikis/macropad/blob/main/docs/cli.md
[service]: https://github.com/rafaelglikis/macropad/blob/main/docs/service.md
[security]: https://github.com/rafaelglikis/macropad/blob/main/docs/security.md
[architecture]: https://github.com/rafaelglikis/macropad/blob/main/docs/architecture.md
[releasing]: https://github.com/rafaelglikis/macropad/blob/main/RELEASING.md
[license]: https://github.com/rafaelglikis/macropad/blob/main/LICENSE
