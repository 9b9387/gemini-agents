import sys
import threading

import questionary
from questionary.constants import DEFAULT_SELECTED_POINTER
from websockets.sync.client import connect

from ..constants import (
    GATEWAY_URI,
    METHOD_CHAT,
    METHOD_REGISTER,
    MSG_TYPE_REQ,
    MSG_TYPE_RES,
    ROLE_CLI,
)
from ..logging_config import setup_logging
from ..protocol import Message


def listen_loop(ws):
    try:
        for message_str in ws:
            msg = Message.from_json(message_str)
            if msg.type == MSG_TYPE_RES and msg.content:
                print(f"\n\033[35mgemini-agents << \033[0m{msg.content}")
                sys.stdout.flush()
    except Exception:
        print("\nConnection lost or closed.")
        sys.exit(1)


def main():
    setup_logging()
    uri = GATEWAY_URI
    sender_id = f"cli_{id(uri)}"  # Simple unique sender ID

    try:
        ws = connect(uri)
        # Register as CLI
        ws.send(
            Message(
                type=MSG_TYPE_REQ,
                method=METHOD_REGISTER,
                role=ROLE_CLI,
                session_id="default_session",
                sender_id=sender_id,
            ).to_json()
        )
    except Exception as e:
        print(f"Could not connect to gateway at {uri}: {e}")
        return

    # Start listening thread for agent responses
    listener_thread = threading.Thread(target=listen_loop, args=(ws,), daemon=True)
    listener_thread.start()

    while True:
        try:
            query = questionary.text("", qmark=DEFAULT_SELECTED_POINTER).ask()
            if query is None:  # Handle Ctrl-C
                break

            cmd = query.strip()
            if cmd.lower() in ("q", "exit", ""):
                break

            # Send the request to the agent
            msg = Message(
                type=MSG_TYPE_REQ,
                method=METHOD_CHAT,
                role=ROLE_CLI,
                session_id="default_session",
                sender_id=sender_id,
                content=query,
            )
            ws.send(msg.to_json())

        except (EOFError, KeyboardInterrupt):
            break

    ws.close()


if __name__ == "__main__":
    main()
