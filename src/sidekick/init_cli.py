"""Sidekick first-run bootstrap.

Creates a Chronary agent + default calendar, writes the IDs to
~/.config/sidekick/config.json, and prints them so they can be dropped
into .env (CHRONARY_AGENT_ID, CHRONARY_CALENDAR_ID).

Usage:
    export CHRONARY_API_KEY=chr_sk_...
    sidekick-init
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

from . import paths


def _id_of(obj: Any) -> Any:
    """Chronary SDK objects may be Pydantic models or plain dicts; tolerate both."""
    if isinstance(obj, dict):
        return obj["id"]
    return obj.id


def main() -> None:
    api_key = os.environ.get("CHRONARY_API_KEY")
    if not api_key:
        print(
            "CHRONARY_API_KEY is not set. Get an org key from "
            "https://console.chronary.ai and export it before running.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from chronary import Chronary
    except ImportError:
        print(
            "The `chronary` package isn't installed. Run: pip install chronary",
            file=sys.stderr,
        )
        sys.exit(1)

    client = Chronary(api_key=api_key)
    timezone = os.getenv("TIMEZONE", "America/Chicago")

    print("Creating Chronary agent for sidekick...")
    agent = client.agents.create(name="sidekick", type="ai")
    agent_id = _id_of(agent)
    print(f"  agent_id = {agent_id}")

    print("Creating default calendar...")
    calendar = client.agents.calendars.create(
        agent_id,
        name="Sidekick",
        timezone=timezone,
    )
    calendar_id = _id_of(calendar)
    print(f"  calendar_id = {calendar_id}")

    # Same file the agent reads (honors CONFIG_FILE / SIDEKICK_CONFIG_DIR).
    config_path = Path(paths.personality_file())
    config_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            existing = {}

    existing["chronary_agent_id"] = agent_id
    existing["chronary_calendar_id"] = calendar_id
    config_path.write_text(json.dumps(existing, indent=2))

    print()
    print(f"Wrote {config_path}")
    print()
    print("Add these to your .env file (or export them):")
    print(f"  CHRONARY_AGENT_ID={agent_id}")
    print(f"  CHRONARY_CALENDAR_ID={calendar_id}")


if __name__ == "__main__":
    main()
