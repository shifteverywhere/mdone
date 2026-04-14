"""
Shell completion script generator.

Generates static completion scripts for bash, zsh, and fish.
Click's built-in shell completion is used as the engine; this module
provides the install-path logic and the `mdone completions` CLI command.

Usage
-----
    mdone completions --shell bash   # print script to stdout
    mdone completions --shell zsh    # print script to stdout
    mdone completions --shell fish   # print script to stdout
    mdone completions --install      # auto-detect shell and install
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Script generation via Click's _COMPLETE env-var mechanism
# ---------------------------------------------------------------------------

# Click generates completion scripts when the PROGNAME_COMPLETE env var is set.
# We wrap that here so the user never has to know the internals.

_SHELL_SOURCE_CMD = {
    "bash": 'eval "$(_MDONE_COMPLETE=bash_source mdone)"',
    "zsh":  'eval "$(_MDONE_COMPLETE=zsh_source mdone)"',
    "fish": "_MDONE_COMPLETE=fish_source mdone | source",
}

# Where each shell sources its completions from
_INSTALL_PATHS = {
    "bash": [
        Path.home() / ".bash_completion.d" / "mdone",
        Path("/etc/bash_completion.d/mdone"),
    ],
    "zsh": [
        Path.home() / ".zsh" / "completions" / "_mdone",
        Path.home() / ".oh-my-zsh" / "completions" / "_mdone",
    ],
    "fish": [
        Path.home() / ".config" / "fish" / "completions" / "mdone.fish",
    ],
}

_RC_FILES = {
    "bash": Path.home() / ".bashrc",
    "zsh":  Path.home() / ".zshrc",
}


def get_script(shell: str, prog_name: str = "mdone") -> str:
    """
    Return the completion script text for *shell*.

    We invoke the CLI itself with the Click completion env var set
    so the output is always in sync with the actual command definitions.
    """
    env_key = f"_{prog_name.upper()}_COMPLETE"
    env_val = f"{shell}_source"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "todo.cli"],
            env={**os.environ, env_key: env_val},
            capture_output=True,
            text=True,
        )
        if result.stdout:
            return result.stdout
    except Exception:
        pass
    # Fallback: return a sourcing stub so the user can at least get started
    return _SHELL_SOURCE_CMD.get(shell, f"# completion not available for {shell}")


def detect_shell() -> str:
    """Detect the current interactive shell from $SHELL."""
    shell_path = os.environ.get("SHELL", "")
    for shell in ("bash", "zsh", "fish"):
        if shell in shell_path:
            return shell
    return "bash"


def install(shell: str, prog_name: str = "mdone") -> tuple:
    """
    Install the completion script for *shell*.

    Returns (success: bool, message: str).
    """
    script = get_script(shell, prog_name)
    candidates = _INSTALL_PATHS.get(shell, [])

    # Try each candidate path in order
    for dest in candidates:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(script)

            # For bash/zsh also suggest sourcing
            rc = _RC_FILES.get(shell)
            source_line = _source_line(shell, dest)
            return True, (
                f"Completion script installed to {dest}\n"
                + (f"Add to {rc}:\n  {source_line}" if rc else "")
            )
        except PermissionError:
            continue

    return False, (
        f"Could not install to any standard location for {shell}.\n"
        f"Run `mdone completions --shell {shell}` and source the output manually."
    )


def _source_line(shell: str, path: Path) -> str:
    if shell == "bash":
        return f"source {path}"
    if shell == "zsh":
        return f"fpath=({path.parent} $fpath); autoload -Uz compinit && compinit"
    if shell == "fish":
        return f"source {path}"
    return f"source {path}"
