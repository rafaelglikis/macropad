# Install

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

## pipx

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

## uv

If `uv` is already installed, its tool interface provides the same isolated installation:

```bash
uv tool install poor-mans-macropad
```

To include desktop notifications, install `poor-mans-macropad[notifications]` instead.

## Optional Desktop Notifications

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

## Input Permissions

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

## Uninstall

Remove the service before uninstalling the tool. See [Uninstall](service.md#uninstall).
