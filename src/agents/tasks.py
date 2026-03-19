import json
from pathlib import Path
from .constants import TASKS_DIR

class TaskManager:
    def __init__(self):
        TASKS_DIR.mkdir(exist_ok=True)

    def _next_id(self) -> int:
        ids = []
        for file_path in TASKS_DIR.glob("task_*.json"):
            try:
                ids.append(int(file_path.stem.split("_")[1]))
            except Exception:
                pass
        return max(ids, default=0) + 1

    def _load(self, task_id: int) -> dict:
        path = TASKS_DIR / f"task_{task_id}.json"
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text())

    def _save(self, task: dict):
        (TASKS_DIR / f"task_{task['id']}.json").write_text(json.dumps(task, indent=2))

    def create(self, subject: str, description: str = "") -> str:
        task = {
            "id": self._next_id(),
            "subject": subject,
            "description": description,
            "status": "pending",
            "owner": None,
            "blockedBy": [],
            "blocks": [],
        }
        self._save(task)
        return json.dumps(task, indent=2)

    def get(self, task_id: int) -> str:
        return json.dumps(self._load(task_id), indent=2)

    def update(
        self,
        task_id: int,
        status: str = None,
        add_blocked_by: list[int] = None,
        add_blocks: list[int] = None,
    ) -> str:
        task = self._load(task_id)
        if status:
            if status not in ("pending", "in_progress", "completed", "deleted"):
                raise ValueError(f"Invalid status: {status}")
            task["status"] = status
            if status == "completed":
                for file_path in TASKS_DIR.glob("task_*.json"):
                    other = json.loads(file_path.read_text())
                    if task_id in other.get("blockedBy", []):
                        other["blockedBy"].remove(task_id)
                        self._save(other)
            if status == "deleted":
                (TASKS_DIR / f"task_{task_id}.json").unlink(missing_ok=True)
                return f"Task {task_id} deleted"

        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if add_blocks:
            task["blocks"] = list(set(task["blocks"] + add_blocks))
        self._save(task)
        return json.dumps(task, indent=2)

    def list_all(self) -> str:
        tasks = [json.loads(f.read_text()) for f in sorted(TASKS_DIR.glob("task_*.json"))]
        if not tasks:
            return "No tasks."
        lines = []
        for task in tasks:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(task["status"], "[?]")
            owner = f" @{task['owner']}" if task.get("owner") else ""
            blocked = f" (blocked by: {task['blockedBy']})" if task.get("blockedBy") else ""
            lines.append(f"{marker} #{task['id']}: {task['subject']}{owner}{blocked}")
        return "\n".join(lines)

    def claim(self, task_id: int, owner: str) -> str:
        task = self._load(task_id)
        task["owner"] = owner
        task["status"] = "in_progress"
        self._save(task)
        return f"Claimed task #{task_id} for {owner}"
