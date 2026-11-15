"""使 `python -m benchmark <子命令>` 可用。"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
