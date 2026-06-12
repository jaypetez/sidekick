from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sidekick")
except PackageNotFoundError:  # pragma: no cover - only when running from a non-installed tree
    __version__ = "0.0.0"
