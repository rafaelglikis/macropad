# Service

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

## Uninstall

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
