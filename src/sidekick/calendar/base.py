"""Calendar provider abstraction.

The method surface mirrors the MCP tool surface exposed to Claude
(list_events, create_event, update_event, delete_event). Step 3 will
delete the Google implementation and ship ChronaryProvider as the
only concrete impl.

Each method accepts the raw dict arguments Claude passes via tool
calls; this keeps the boundary with mcp_server.py simple.
"""

from abc import ABC, abstractmethod


class CalendarProvider(ABC):
    @abstractmethod
    def list_events(self, args: dict) -> list[dict]: ...

    @abstractmethod
    def create_event(self, args: dict) -> dict: ...

    @abstractmethod
    def update_event(self, args: dict) -> dict: ...

    @abstractmethod
    def delete_event(self, args: dict) -> dict: ...
