"""Sync ML model files from statistical-drafting repo into models/ directory."""

import shutil
import os

SRC = os.path.expanduser("~/statistical-drafting/data")
DST = os.path.join(os.path.dirname(__file__), "models")


def sync():
    for subdir in ("onnx", "cards"):
        src_dir = os.path.join(SRC, subdir)
        dst_dir = os.path.join(DST, subdir)
        if not os.path.isdir(src_dir):
            print(f"Source not found: {src_dir}")
            continue
        os.makedirs(dst_dir, exist_ok=True)

        ext = ".onnx" if subdir == "onnx" else ".csv"
        count = 0
        for f in os.listdir(src_dir):
            if f.endswith(ext):
                shutil.copy2(os.path.join(src_dir, f), os.path.join(dst_dir, f))
                count += 1
        print(f"Synced {count} {ext} files to {dst_dir}")


if __name__ == "__main__":
    sync()
