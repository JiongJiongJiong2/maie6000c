"""Run the isolated experiment: python scripts/run_meme_agent.py [--port 8010]."""

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument(
        "--data-root", type=Path, help="Optional separate local collection directory"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    if args.data_root:
        os.environ["DATA_ROOT"] = str(args.data_root.resolve())
    import uvicorn

    print(f"Meme search v1: http://127.0.0.1:{args.port}/studio/", flush=True)
    uvicorn.run("services.meme_agent.app:app", host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
