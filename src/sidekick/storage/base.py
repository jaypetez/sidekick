"""Task store abstraction.

Method surface mirrors today's MCP task tools. Step 4 replaces the
Google impl with a local SQLite store.
"""

from abc import ABC, abstractmethod
from typing import Any


class TaskStore(ABC):
    @abstractmethod
    def list_task_lists(self, args: dict[str, Any]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def list_tasks(self, args: dict[str, Any]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def add_tasks(self, args: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def complete_task(self, args: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def delete_task(self, args: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def clear_completed(self, args: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def delete_task_list(self, args: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def rename_task_list(self, args: dict[str, Any]) -> dict[str, Any]: ...
