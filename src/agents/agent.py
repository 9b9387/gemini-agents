import json
import os
from google import genai
from google.genai import types
from loguru import logger
from .logging_config import setup_logging
from .constants import MODEL_ID, TOKEN_THRESHOLD, SKILLS_DIR
from .todo import TodoManager
from .skills import SkillLoader
from .tasks import TaskManager
from .background import BackgroundManager
from .messaging import MessageBus
from .team import TeammateManager
from .context import microcompact, estimate_tokens, auto_compact
from .tools import get_tool_handlers, TOOLS

def agent_loop(client, history, todo_mgr, bg_mgr, bus, tool_handlers, generate_config):
    rounds_without_todo = 0
    while True:
        microcompact(history)
        if estimate_tokens(history) > TOKEN_THRESHOLD:
            logger.info("[auto-compact triggered]")
            history[:] = auto_compact(client, history)

        notifs = bg_mgr.drain()
        if notifs:
            text = "\n".join(f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs)
            history.append(types.Content(role="user", parts=[types.Part.from_text(text=f"<background-results>\n{text}\n</background-results>")]))
            history.append(types.Content(role="model", parts=[types.Part.from_text(text="Noted background results.")]))

        inbox = bus.read_inbox("lead")
        if inbox:
            history.append(types.Content(role="user", parts=[types.Part.from_text(text=f"<inbox>{json.dumps(inbox, indent=2)}</inbox>")]))
            history.append(types.Content(role="model", parts=[types.Part.from_text(text="Noted inbox messages.")]))

        response = client.models.generate_content(
            model=MODEL_ID,
            contents=history,
            config=generate_config,
        )
        history.append(response.candidates[0].content)
        if not response.function_calls:
            return

        used_todo = False
        manual_compress = False
        result_parts = []
        for function_call in response.function_calls:
            if function_call.name == "compress":
                manual_compress = True
            handler = tool_handlers.get(function_call.name)
            try:
                output = handler(**dict(function_call.args)) if handler else f"Unknown tool: {function_call.name}"
            except Exception as e:
                output = f"Error: {e}"
            logger.info(f"Tool call: {function_call.name}({dict(function_call.args)}) -> {str(output)[:200]}")
            result_parts.append(
                types.Part.from_function_response(
                    name=function_call.name,
                    response={"output": str(output)},
                )
            )
            if function_call.name == "TodoWrite":
                used_todo = True

        rounds_without_todo = 0 if used_todo else rounds_without_todo + 1
        history.append(types.Content(role="user", parts=result_parts))

        if todo_mgr.has_open_items() and rounds_without_todo >= 3:
            history.append(types.Content(role="user", parts=[types.Part.from_text(text="<reminder>Update your todos.</reminder>")]))
            rounds_without_todo = 0

        if manual_compress:
            logger.info("[manual compact]")
            history[:] = auto_compact(client, history)

def print_history(history: list[types.Content]):
    for idx, content in enumerate(history):
        role = content.role
        lines = []
        for part in (content.parts or []):
            if hasattr(part, "text") and part.text:
                lines.append(part.text)
            elif hasattr(part, "function_call") and part.function_call:
                function_call = part.function_call
                lines.append(f"[function_call] {function_call.name}({dict(function_call.args)})")
            elif hasattr(part, "function_response") and part.function_response:
                function_response = part.function_response
                lines.append(f"[function_response] {function_response.name} -> {dict(function_response.response)}")
        print(f"{idx} [{role}]: {chr(10).join(lines) or '(empty)'}\n")

from dotenv import load_dotenv

def main():
    setup_logging()
    load_dotenv()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    todo_mgr = TodoManager()
    skill_loader = SkillLoader(SKILLS_DIR)
    task_mgr = TaskManager()
    bg_mgr = BackgroundManager()
    bus = MessageBus()
    team_mgr = TeammateManager(client, bus, task_mgr)

    tool_handlers = get_tool_handlers(todo_mgr, skill_loader, task_mgr, bg_mgr, bus, team_mgr, client)
    
    system_instruction = f"You are a coding agent. Use tools to solve tasks. Skills: {skill_loader.descriptions()}"
    generate_config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[TOOLS],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    history = []
    while True:
        try:
            query = input("\033[36mgemini-agents >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        cmd = query.strip()
        if cmd.lower() in ("q", "exit", ""):
            break
        if cmd == "/compact":
            if history:
                logger.info("[manual compact via /compact]")
                history[:] = auto_compact(client, history)
            continue
        if cmd == "/tasks":
            print(task_mgr.list_all())
            continue
        if cmd == "/team":
            print(team_mgr.list_all())
            continue
        if cmd == "/inbox":
            print(json.dumps(bus.read_inbox("lead"), indent=2))
            continue
        if cmd.lower() in ("history", "h"):
            print_history(history)
            continue

        history.append(types.Content(role="user", parts=[types.Part.from_text(text=query)]))
        agent_loop(client, history, todo_mgr, bg_mgr, bus, tool_handlers, generate_config)

        last_content = history[-1]
        for part in (last_content.parts or []):
            if hasattr(part, "text") and part.text:
                print(part.text)
        print()

if __name__ == "__main__":
    main()
