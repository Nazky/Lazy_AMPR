"""Frozen entry point for the AMPR trace-profile command-line helper."""

import multiprocessing

from ampr_pack_profile import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
