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
        from chronary import Chronary  # type: ignore[import-not-found]
    except ImportError:
        print(
            "The `chronary` package isn't installed. Run: pip install chronary",
            file=sys.stderr,
        )
        sys.exit(1)

    client = Chronary(api_key=api_key)
    timezone = os.getenv("TIMEZONE", "America/Chicago")

    print("Creating Chronary agent for sidekick...")
    agent = client.agents.create(name="sidekick")
    agent_id = getattr(agent, "id", None) or agent["id"]
    print(f"  agent_id = {agent_id}")

    print("Creating default calendar...")
    calendar = client.agents.calendars.create(
        agent_id,
        name="Sidekick",
        timezone=timezone,
    )
    calendar_id = getattr(calendar, "id", None) or calendar["id"]
    print(f"  calendar_id = {calendar_id}")

    config_dir = Path(
        os.getenv("SIDEKICK_CONFIG_DIR", os.path.expanduser("~/.config/sidekick"))
    )
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"

    existing: dict = {}
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
