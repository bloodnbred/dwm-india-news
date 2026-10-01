"""Entry point so the CLI runs as `python -m dwm`.

Chosen over a Makefile because a Makefile is awkward on Windows
(BLUEPRINT section 1, task runner decision).
"""

from dwm.cli import main

if __name__ == "__main__":
    main()
