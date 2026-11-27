"""Verify all bytes, identities, unit pages and indices in a local v2 generation."""

import argparse
import json
from pathlib import Path
import sys

from release_v2 import verify


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release")
    args = parser.parse_args(argv)
    try:
        result = verify(args.root, args.release)
        print(json.dumps({"releaseId": result["manifest"]["releaseId"], "details": result["details"], "files": result["files"]}))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(f"v2 verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
