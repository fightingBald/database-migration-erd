"""The primary module entrypoint generates D2 by default."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(default_format="d2"))
