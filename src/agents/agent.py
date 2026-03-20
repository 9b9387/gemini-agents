import json
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types
from loguru import logger
from websockets.sync.client import connect

from .background import BackgroundManager
from .constants import (
    GATEWAY_URI,
    METHOD_CHAT,
    METHOD_CHAT_RES,
    METHOD_REGISTER,
    MODEL_ID,
    MSG_TYPE_REQ,
    MSG_TYPE_RES,
    ROLE_AGENT,
    SKILLS_DIR,
    TOKEN_THRESHOLD,
)
from .context import auto_compact, estimate_tokens, microcompact
from .logging_config import setup_logging
from .messaging import MessageBus
from .protocol import Message
from .skills import SkillLoader
from .tasks import TaskManager
from .team import TeammateManager
from .todo import TodoManager
from .tools import TOOLS, get_tool_handlers


def agent_loop(client, history, todo_mgr, bg_mgr, bus, tool_handlers, generate_config):
    rounds_without_todo = 0
    while True:
        microcompact(history)
        if estimate_tokens(history) > TOKEN_THRESHOLD:
            logger.info("[auto-compact triggered]")
            history[:] = auto_compact(client, history)

        notifs = bg_mgr.drain()
        if notifs:
            text = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs
            )
            logger.debug(f"Background notifications: {text}")
            history.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text=f"<background-results>\n{text}\n</background-results>"
                        )
                    ],
                )
            )
            history.append(
                types.Content(
                    role="model",
                    parts=[types.Part.from_text(text="Noted background results.")],
                )
            )

        inbox = bus.read_inbox("lead")
        if inbox:
            history.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text=f"<inbox>{json.dumps(inbox, indent=2)}</inbox>"
                        )
                    ],
                )
            )
            history.append(
                types.Content(
                    role="model",
                    parts=[types.Part.from_text(text="Noted inbox messages.")],
                )
            )

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
                output = (
                    handler(**dict(function_call.args))
                    if handler
                    else f"Unknown tool: {function_call.name}"
                )
            except Exception as e:
                output = f"Error: {e}"
            logger.debug(
                f"Tool call: {function_call.name}({dict(function_call.args)}) "
                f"-> {str(output)[:200]}"
            )
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
            history.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text="<reminder>Update your todos.</reminder>")
                    ],
                )
            )
            rounds_without_todo = 0

        if manual_compress:
            logger.info("[manual compact]")
            history[:] = auto_compact(client, history)


def format_history(history: list[types.Content]) -> str:
    output = []
    for idx, content in enumerate(history):
        role = content.role
        lines = []
        for part in content.parts or []:
            if hasattr(part, "text") and part.text:
                lines.append(part.text)
            elif hasattr(part, "function_call") and part.function_call:
                function_call = part.function_call
                lines.append(
                    f"[function_call] {function_call.name}({dict(function_call.args)})"
                )
            elif hasattr(part, "function_response") and part.function_response:
                function_response = part.function_response
                lines.append(
                    f"[function_response] {function_response.name} -> "
                    f"{dict(function_response.response)}"
                )
        output.append(f"{idx} [{role}]: {chr(10).join(lines) or '(empty)'}\n")
    return "\n".join(output)


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

    tool_handlers = get_tool_handlers(
        todo_mgr, skill_loader, task_mgr, bg_mgr, bus, team_mgr, client
    )

    system_instruction = (
        f"You are a coding agent. Use tools to solve tasks. "
        f"Skills: {skill_loader.descriptions()}. "
        f"IMPORTANT: "
        f"Never end a turn with only a tool result; always explain what was found or done. Provide a clear, helpful summary or response to the user."
    )
    generate_config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[TOOLS],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    history = []
    uri = GATEWAY_URI
    sender_id = f"agent_{id(uri)}"

    # Try connecting with a retry loop
    connected = False
    for _ in range(5):
        try:
            ws = connect(uri)
            ws.send(
                Message(
                    type=MSG_TYPE_REQ,
                    method=METHOD_REGISTER,
                    role=ROLE_AGENT,
                    session_id="global",
                    sender_id=sender_id,
                ).to_json()
            )
            logger.info("Agent connected to gateway.")
            connected = True
            break
        except Exception as e:
            logger.warning(f"Gateway not available yet, retrying in 2s... ({e})")
            time.sleep(2)

    if not connected:
        logger.error("Could not connect to gateway. Exiting.")
        return

    try:
        for message_str in ws:
            msg = Message.from_json(message_str)
            if msg.type == MSG_TYPE_REQ and msg.method == METHOD_CHAT:
                query = msg.content
                cmd = query.strip()

                # Common response factory
                def send_response(content):
                    ws.send(
                        Message(
                            type=MSG_TYPE_RES,
                            method=METHOD_CHAT_RES,
                            role=ROLE_AGENT,
                            session_id=msg.session_id,
                            sender_id=sender_id,
                            reply_to=msg.id,
                            content=content,
                        ).to_json()
                    )

                # Handle special commands
                if cmd == "/compact":
                    if history:
                        logger.info("[manual compact via /compact]")
                        history[:] = auto_compact(client, history)
                        send_response("History compacted.")
                    continue
                if cmd == "/tasks":
                    tasks = task_mgr.list_all()
                    send_response(str(tasks))
                    continue
                if cmd == "/team":
                    team = team_mgr.list_all()
                    send_response(str(team))
                    continue
                if cmd == "/inbox":
                    inbox = json.dumps(bus.read_inbox("lead"), indent=2)
                    send_response(inbox)
                    continue
                if cmd.lower() in ("history", "h"):
                    hist_str = format_history(history)
                    send_response(hist_str)
                    continue

                # Normal generation
                history.append(
                    types.Content(role="user", parts=[types.Part.from_text(text=query)])
                )
                logger.debug(f"User query: {query}")

                agent_loop(
                    client,
                    history,
                    todo_mgr,
                    bg_mgr,
                    bus,
                    tool_handlers,
                    generate_config,
                )

                last_content = history[-1]
                response_texts = []
                for part in last_content.parts or []:
                    if hasattr(part, "text") and part.text:
                        response_texts.append(part.text)

                final_response = "\n".join(response_texts)
                if final_response:
                    send_response(final_response)

    except KeyboardInterrupt:
        logger.info("Agent stopped by user.")
    except Exception as e:
        logger.error(f"Connection lost: {e}")
    finally:
        ws.close()


if __name__ == "__main__":
    main()
