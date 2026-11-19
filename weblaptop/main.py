"""
Application entrypoint for weblaptop.
"""

import sys
from weblaptop.cli import run_cli


def main() -> None:
    """Main function called by entry points."""
    sys.exit(run_cli())


if __name__ == "__main__":
    main()
