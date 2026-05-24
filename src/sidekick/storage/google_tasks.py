"""Google Tasks concrete TaskStore.

Mirrors the API previously inlined in `mcp_server.MCPServer`. Step 4
replaces this with a local SQLite implementation.
"""

from .base import TaskStore


class GoogleTasksStore(TaskStore):
    def __init__(self, tasks_service) -> None:
        self.tasks = tasks_service

    def find_task_list(self, list_name: str) -> str | None:
        result = self.tasks.tasklists().list().execute()
        for tl in result.get("items", []):
            if tl["title"].lower() == list_name.lower():
                return tl["id"]
        return None

    def get_or_create_task_list(self, list_name: str) -> str:
        list_id = self.find_task_list(list_name)
        if list_id:
            return list_id
        new_list = self.tasks.tasklists().insert(body={"title": list_name}).execute()
        return new_list["id"]

    def find_task_by_title(self, list_id: str, title: str) -> dict | None:
        result = self.tasks.tasks().list(tasklist=list_id, showCompleted=False).execute()
        title_lower = title.lower()
        for task in result.get("items", []):
            if title_lower in task.get("title", "").lower():
                return task
        return None

    def list_tasks(self, args: dict) -> list[dict]:
        list_id = self.get_or_create_task_list(args["list_name"])
        result = self.tasks.tasks().list(tasklist=list_id, showCompleted=False).execute()
        return [
            {"title": t.get("title", ""), "status": t.get("status", "")}
            for t in result.get("items", [])
        ]

    def add_tasks(self, args: dict) -> dict:
        list_id = self.get_or_create_task_list(args["list_name"])
        added = []
        for item in args["items"]:
            task = self.tasks.tasks().insert(
                tasklist=list_id, body={"title": item}
            ).execute()
            added.append(task.get("title", ""))
        return {"status": "added", "items": added, "list": args["list_name"]}

    def complete_task(self, args: dict) -> dict:
        list_id = self.get_or_create_task_list(args["list_name"])
        task = self.find_task_by_title(list_id, args["task_title"])
        if not task:
            return {"error": f"No task matching '{args['task_title']}' found in {args['list_name']}"}
        task["status"] = "completed"
        self.tasks.tasks().update(tasklist=list_id, task=task["id"], body=task).execute()
        return {"status": "completed", "title": task["title"]}

    def delete_task(self, args: dict) -> dict:
        list_id = self.get_or_create_task_list(args["list_name"])
        task = self.find_task_by_title(list_id, args["task_title"])
        if not task:
            return {"error": f"No task matching '{args['task_title']}' found in {args['list_name']}"}
        self.tasks.tasks().delete(tasklist=list_id, task=task["id"]).execute()
        return {"status": "deleted", "title": task["title"]}

    def clear_completed(self, args: dict) -> dict:
        list_id = self.get_or_create_task_list(args["list_name"])
        self.tasks.tasks().clear(tasklist=list_id).execute()
        return {"status": "cleared", "list": args["list_name"]}

    def list_task_lists(self, args: dict) -> list[dict]:
        result = self.tasks.tasklists().list().execute()
        return [
            {"title": tl.get("title", ""), "id": tl.get("id", "")}
            for tl in result.get("items", [])
        ]

    def delete_task_list(self, args: dict) -> dict:
        list_id = self.find_task_list(args["list_name"])
        if not list_id:
            return {"error": f"Task list '{args['list_name']}' not found"}
        self.tasks.tasklists().delete(tasklist=list_id).execute()
        return {"status": "deleted", "list": args["list_name"]}

    def rename_task_list(self, args: dict) -> dict:
        list_id = self.find_task_list(args["list_name"])
        if not list_id:
            return {"error": f"Task list '{args['list_name']}' not found"}
        self.tasks.tasklists().patch(
            tasklist=list_id, body={"title": args["new_name"]}
        ).execute()
        return {"status": "renamed", "old_name": args["list_name"], "new_name": args["new_name"]}
