"""Task store abstraction.

Method surface mirrors today's MCP task tools. Step 4 replaces the
Google impl with a local SQLite store.
"""

from abc import ABC, abstractmethod


class TaskStore(ABC):
    @abstractmethod
    def list_task_lists(self, args: dict) -> list[dict]: ...

    @abstractmethod
    def list_tasks(self, args: dict) -> list[dict]: ...

    @abstractmethod
    def add_tasks(self, args: dict) -> dict: ...

    @abstractmethod
    def complete_task(self, args: dict) -> dict: ...

    @abstractmethod
    def delete_task(self, args: dict) -> dict: ...

    @abstractmethod
    def clear_completed(self, args: dict) -> dict: ...

    @abstractmethod
    def delete_task_list(self, args: dict) -> dict: ...

    @abstractmethod
    def rename_task_list(self, args: dict) -> dict: ...
