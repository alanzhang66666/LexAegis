"""Child process for GPU OCR/transcription so the helper exits and releases VRAM."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 4 or args[0] != "parse":
        print("usage: python -m lexaegis.gpu_aux parse <path> <document_id> <version>", file=sys.stderr)
        return 2
    from .parsing import parse

    result = parse(Path(args[1]), args[2], int(args[3]))
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
