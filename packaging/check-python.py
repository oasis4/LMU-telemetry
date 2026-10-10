"""Validate the build interpreter without inline shell quoting."""
import struct
import sys


def main():
    if sys.version_info[:2] != (3, 13) or struct.calcsize('P') != 8:
        print(f'Python 3.13 x64 required; found {sys.version.split()[0]} '
              f'({struct.calcsize("P") * 8}-bit).', file=sys.stderr)
        return 1
    print(sys.executable)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
