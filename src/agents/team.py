import json
import threading
import time
import uuid
from google.genai import types
from .constants import TEAM_DIR, WORKDIR, MODEL_ID, IDLE_TIMEOUT, POLL_INTERVAL, TASKS_DIR
from .utils import run_bash, run_read, run_write, run_edit

class TeammateManager:
    def __init__(self, client, bus, task_mgr):
        TEAM_DIR.mkdir(exist_ok=True)
        self.client = client
        self.bus = bus
        self.task_mgr = task_mgr
        self.config_path = TEAM_DIR / "config.json"
        self.config = self._load()
        self.threads = {}
        self.shutdown_requests = {}
        self.plan_requests = {}

    def _load(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"team_name": "default", "members": []}

    def _save(self):
        self.config_path.write_text(json.dumps(self.config, indent=2))

    def _find(self, name: str) -> dict | None:
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def spawn(self, name: str, role: str, prompt: str) -> str:
        member = self._find(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save()

        thread = threading.Thread(target=self._loop, args=(name, role, prompt), daemon=True)
        self.threads[name] = thread
        thread.start()
        return f"Spawned '{name}' (role: {role})"

    def _set_status(self, name: str, status: str):
        member = self._find(name)
        if member:
            member["status"] = status
            self._save()

    def _teammate_tools(self) -> types.Tool:
        return types.Tool(function_declarations=[
            {
                "name": "bash",
                "description": "Run command.",
                "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
            },
            {
                "name": "read_file",
                "description": "Read file.",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            },
            {
                "name": "write_file",
                "description": "Write file.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"],
                },
            },
            {
                "name": "edit_file",
                "description": "Edit file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            },
            {
                "name": "send_message",
                "description": "Send message.",
                "parameters": {
                    "type": "object",
                    "properties": {"to": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["to", "content"],
                },
            },
            {"name": "idle", "description": "Signal no more work.", "parameters": {"type": "object", "properties": {}}},
            {
                "name": "claim_task",
                "description": "Claim task by ID.",
                "parameters": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]},
            },
            {
                "name": "shutdown_response",
                "description": "Respond to shutdown request.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string"},
                        "approve": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["request_id", "approve"],
                },
            },
            {
                "name": "plan_approval",
                "description": "Submit a plan for approval.",
                "parameters": {
                    "type": "object",
                    "properties": {"plan": {"type": "string"}},
                    "required": ["plan"],
                },
            },
        ])

    def _exec(self, sender: str, tool_name: str, args: dict) -> str:
        if tool_name == "bash":
            return run_bash(args["command"])
        if tool_name == "read_file":
            return run_read(args["path"], args.get("limit"))
        if tool_name == "write_file":
            return run_write(args["path"], args["content"])
        if tool_name == "edit_file":
            return run_edit(args["path"], args["old_text"], args["new_text"])
        if tool_name == "send_message":
            return self.bus.send(sender, args["to"], args["content"])
        if tool_name == "claim_task":
            return self.task_mgr.claim(args["task_id"], sender)
        if tool_name == "shutdown_response":
            request_id = args["request_id"]
            approve = args["approve"]
            if request_id in self.shutdown_requests:
                self.shutdown_requests[request_id]["status"] = "approved" if approve else "rejected"
            self.bus.send(
                sender,
                "lead",
                args.get("reason", ""),
                "shutdown_response",
                {"request_id": request_id, "approve": approve},
            )
            return f"Shutdown {'approved' if approve else 'rejected'}"
        if tool_name == "plan_approval":
            plan_text = args.get("plan", "")
            request_id = str(uuid.uuid4())[:8]
            self.plan_requests[request_id] = {"from": sender, "plan": plan_text, "status": "pending"}
            self.bus.send(
                sender,
                "lead",
                plan_text,
                "plan_approval_response",
                {"request_id": request_id, "plan": plan_text},
            )
            return f"Plan submitted (request_id={request_id}). Waiting for approval."
        return f"Unknown tool: {tool_name}"

    def _loop(self, name: str, role: str, prompt: str):
        team_name = self.config["team_name"]
        sys_prompt = (
            f"You are '{name}', role: {role}, team: {team_name}, at {WORKDIR}. "
            "Use idle when done with current work. You may auto-claim tasks."
        )
        config = types.GenerateContentConfig(
            system_instruction=sys_prompt,
            tools=[self._teammate_tools()],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        history = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]

        while True:
            for _ in range(50):
                inbox = self.bus.read_inbox(name)
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        self._set_status(name, "shutdown")
                        return
                    history.append(types.Content(role="user", parts=[types.Part.from_text(text=json.dumps(msg))]))

                try:
                    response = self.client.models.generate_content(
                        model=MODEL_ID,
                        contents=history,
                        config=config,
                    )
                except Exception:
                    self._set_status(name, "shutdown")
                    return

                history.append(response.candidates[0].content)
                if not response.function_calls:
                    break

                idle_requested = False
                result_parts = []
                for function_call in response.function_calls:
                    if function_call.name == "idle":
                        idle_requested = True
                        output = "Entering idle phase."
                    else:
                        output = self._exec(name, function_call.name, dict(function_call.args))
                    print(f"  [{name}] {function_call.name}: {str(output)[:120]}")
                    result_parts.append(
                        types.Part.from_function_response(
                            name=function_call.name,
                            response={"output": str(output)},
                        )
                    )

                history.append(types.Content(role="user", parts=result_parts))
                if idle_requested:
                    break

            self._set_status(name, "idle")
            resume = False
            for _ in range(IDLE_TIMEOUT // max(POLL_INTERVAL, 1)):
                time.sleep(POLL_INTERVAL)
                inbox = self.bus.read_inbox(name)
                if inbox:
                    for msg in inbox:
                        if msg.get("type") == "shutdown_request":
                            self._set_status(name, "shutdown")
                            return
                        history.append(types.Content(role="user", parts=[types.Part.from_text(text=json.dumps(msg))]))
                    resume = True
                    break

                unclaimed = []
                for f in sorted(TASKS_DIR.glob("task_*.json")):
                    task = json.loads(f.read_text())
                    if task.get("status") == "pending" and not task.get("owner") and not task.get("blockedBy"):
                        unclaimed.append(task)

                if unclaimed:
                    task = unclaimed[0]
                    self.task_mgr.claim(task["id"], name)
                    if len(history) <= 3:
                        history.insert(
                            0,
                            types.Content(
                                role="user",
                                parts=[types.Part.from_text(text=f"<identity>You are '{name}', role: {role}, team: {team_name}.</identity>")],
                            ),
                        )
                        history.insert(
                            1,
                            types.Content(role="model", parts=[types.Part.from_text(text=f"I am {name}. Continuing.")]),
                        )
                    history.append(
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=f"<auto-claimed>Task #{task['id']}: {task['subject']}\n{task.get('description', '')}</auto-claimed>")],
                        )
                    )
                    history.append(
                        types.Content(
                            role="model",
                            parts=[types.Part.from_text(text=f"Claimed task #{task['id']}. Working on it.")],
                        )
                    )
                    resume = True
                    break

            if not resume:
                self._set_status(name, "shutdown")
                return
            self._set_status(name, "working")

    def list_all(self) -> str:
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for member in self.config["members"]:
            lines.append(f"  {member['name']} ({member['role']}): {member['status']}")
        return "\n".join(lines)

    def member_names(self) -> list[str]:
        return [member["name"] for member in self.config["members"]]

    def handle_shutdown_request(self, teammate: str) -> str:
        request_id = str(uuid.uuid4())[:8]
        self.shutdown_requests[request_id] = {"target": teammate, "status": "pending"}
        self.bus.send("lead", teammate, "Please shut down.", "shutdown_request", {"request_id": request_id})
        return f"Shutdown request {request_id} sent to '{teammate}'"

    def handle_plan_review(self, request_id: str, approve: bool, feedback: str = "") -> str:
        req = self.plan_requests.get(request_id)
        if not req:
            return f"Error: Unknown plan request_id '{request_id}'"
        req["status"] = "approved" if approve else "rejected"
        self.bus.send(
            "lead",
            req["from"],
            feedback,
            "plan_approval_response",
            {"request_id": request_id, "approve": approve, "feedback": feedback},
        )
        return f"Plan {req['status']} for '{req['from']}'"
