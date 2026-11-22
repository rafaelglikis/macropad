# Action Execution And Security

Profile actions are trusted shell code and must never be loaded from an untrusted source. Each
command runs with `shell=True`, starts from `/`, inherits the Macropad process environment, receives
no stdin, and normally has stdout and stderr discarded. Actions are detached and continue across
profile reloads or worker shutdown.

Each keyboard worker tracks at most eight concurrent actions. Additional actions are dropped rather
than queued until an earlier action exits. The systemd user service includes `~/bin`, `~/.local/bin`,
and standard system command directories in its deterministic `PATH`. Use absolute paths or a service
override for commands installed in other interactive-shell or tool-manager directories.
