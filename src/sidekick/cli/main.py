"""Entry point for the ``sidekick-cli`` command.

Builds the argparse tree, dispatches to the subcommand handler, and
turns :class:`CliError` (and Ctrl-C) into clean stderr output + the
appropriate exit code.
"""

from __future__ import annotations

import argparse
import sys

from .client import ApiClient, CliError, default_base_url
from .commands import ALL_GROUPS


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sidekick-cli",
        description="Drive the running sidekick bot from the terminal.",
    )
    parser.add_argument(
        "--base-url",
        help=f"HTTP base URL of the running bot (default: {default_base_url()})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit raw JSON instead of human-readable output",
    )

    subparsers = parser.add_subparsers(dest="group", required=True, metavar="GROUP")
    for module in ALL_GROUPS:
        module.register(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return 2

    try:
        with ApiClient(base_url=args.base_url) as client:
            handler(client, args)
    except CliError as exc:
        sys.stderr.write(f"sidekick-cli: {exc.code}: {exc}\n")
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted.\n")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
