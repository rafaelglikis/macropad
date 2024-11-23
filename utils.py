import os
import resource
import subprocess
import sys
import threading


def reap_zombie_processes(signum, frame):
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
        except ChildProcessError:
            break


def debounce(wait_time):
    """
    Decorator that will debounce a function so that it is called after wait_time seconds
    If it is called multiple times, will wait for the last call to be debounced and run only this one.
    """

    def decorator(function):
        def debounced(*args, **kwargs):
            def call_function():
                debounced._timer = None
                return function(*args, **kwargs)

            # if we already have a call to the function currently waiting to be executed, reset the timer
            if debounced._timer is not None:
                debounced._timer.cancel()

            # after wait_time, call the function provided to the decorator with its arguments
            debounced._timer = threading.Timer(wait_time, call_function)
            debounced._timer.start()

        debounced._timer = None
        return debounced

    return decorator


def daemonize_and_run_command(command: str) -> None:
    """Daemonizes the process and executes the given shell command."""
    try:
        # First fork
        pid = os.fork()
        if pid > 0:
            return  # Parent process returns to continue the loop
    except OSError as e:
        print(f"First fork failed: {e}", file=sys.stderr)
        return

    # Decouple from parent environment
    os.chdir('/')
    os.umask(0)
    os.setsid()

    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        print(f"Second fork failed: {e}", file=sys.stderr)
        sys.exit(1)

    # In the child process

    # Close all file descriptors except stdin(0), stdout(1), stderr(2)
    max_fd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
    if max_fd == resource.RLIM_INFINITY:
        max_fd = 1024  # Set a default if unlimited
    os.closerange(3, max_fd)

    # Redirect standard file descriptors to /dev/null
    sys.stdout.flush()
    sys.stderr.flush()
    with open('/dev/null', 'rb', 0) as read_null, open('/dev/null', 'wb', 0) as write_null:
        os.dup2(read_null.fileno(), sys.stdin.fileno())
        os.dup2(write_null.fileno(), sys.stdout.fileno())
        os.dup2(write_null.fileno(), sys.stderr.fileno())

    try:
        # Execute the command
        pipe = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            close_fds=True
        )
        stdout, _ = pipe.communicate()
    except Exception as e:
        print(f"Failed to execute command: {e}", file=sys.stderr)

    sys.exit(0)
