import subprocess
import threading
import uuid
from queue import Queue
from .constants import WORKDIR

class BackgroundManager:
    def __init__(self):
        self.tasks = {}
        self.notifications = Queue()

    def run(self, command: str, timeout: int = 120) -> str:
        task_id = str(uuid.uuid4())[:8]
        self.tasks[task_id] = {"status": "running", "command": command, "result": None}
        thread = threading.Thread(target=self._execute, args=(task_id, command, timeout), daemon=True)
        thread.start()
        return f"Background task {task_id} started: {command[:80]}"

    def _execute(self, task_id: str, command: str, timeout: int):
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = (result.stdout + result.stderr).strip()[:50000]
            self.tasks[task_id].update({"status": "completed", "result": output or "(no output)"})
        except Exception as e:
            self.tasks[task_id].update({"status": "error", "result": str(e)})

        self.notifications.put(
            {
                "task_id": task_id,
                "status": self.tasks[task_id]["status"],
                "result": str(self.tasks[task_id]["result"])[:500],
            }
        )

    def check(self, task_id: str = None) -> str:
        if task_id:
            task = self.tasks.get(task_id)
            return f"[{task['status']}] {task.get('result', '(running)')}" if task else f"Unknown: {task_id}"
        return (
            "\n".join(f"{k}: [{v['status']}] {v['command'][:60]}" for k, v in self.tasks.items())
            or "No bg tasks."
        )

    def drain(self) -> list[dict]:
        notifs = []
        while not self.notifications.empty():
            notifs.append(self.notifications.get_nowait())
        return notifs
