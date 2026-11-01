#!/usr/bin/env python3
"""Deprecated name, kept so existing scripts keep working: the client is now
cli/ratatosk.py. `securedrop_upload.py FILE --server ...` maps to
`ratatosk.py upload FILE --server ...`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ratatosk import main  # noqa: E402

if __name__ == "__main__":
    print("note: securedrop_upload.py is now 'ratatosk.py upload'", file=sys.stderr)
    sys.exit(main(["upload", *sys.argv[1:]]))
