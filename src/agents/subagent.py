from google.genai import types
from .constants import MODEL_ID
from .utils import run_bash, run_read, run_write, run_edit
from .context import content_to_text

def subagent_tools(agent_type: str) -> types.Tool:
    decls = [
        {
            "name": "bash",
            "description": "Run command.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
        {
            "name": "read_file",
            "description": "Read file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    ]
    if agent_type != "Explore":
        decls += [
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
        ]
    return types.Tool(function_declarations=decls)

def run_subagent(client, prompt: str, agent_type: str = "Explore") -> str:
    handlers = {
        "bash": lambda **kw: run_bash(kw["command"]),
        "read_file": lambda **kw: run_read(kw["path"]),
        "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
        "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    }
    config = types.GenerateContentConfig(
        tools=[subagent_tools(agent_type)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    history = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
    last_content = None

    for _ in range(30):
        response = client.models.generate_content(model=MODEL_ID, contents=history, config=config)
        last_content = response.candidates[0].content
        history.append(last_content)
        if not response.function_calls:
            break

        result_parts = []
        for function_call in response.function_calls:
            handler = handlers.get(function_call.name, lambda **kw: "Unknown tool")
            output = handler(**dict(function_call.args))
            result_parts.append(
                types.Part.from_function_response(
                    name=function_call.name,
                    response={"output": str(output)[:50000]},
                )
            )
        history.append(types.Content(role="user", parts=result_parts))

    return content_to_text(last_content) or "(subagent failed)"
