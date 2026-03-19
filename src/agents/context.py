import json
import time
from google.genai import types
from .constants import TRANSCRIPT_DIR, MODEL_ID
from google import genai

# We'll need a way to get the client here, or pass it in.
# For now, let's assume it's passed or available globally if we import it.
# Actually, it's better to pass the client to auto_compact.

def content_to_text(content: types.Content | None) -> str:
    if not content or not content.parts:
        return ""
    return "".join(part.text for part in content.parts if hasattr(part, "text") and part.text)

def history_to_text(history: list[types.Content]) -> str:
    lines = []
    for content in history:
        lines.append(f"[{content.role}]")
        for part in (content.parts or []):
            if hasattr(part, "text") and part.text:
                lines.append(part.text)
            elif hasattr(part, "function_call") and part.function_call:
                function_call = part.function_call
                lines.append(f"[function_call] {function_call.name}({dict(function_call.args)})")
            elif hasattr(part, "function_response") and part.function_response:
                function_response = part.function_response
                lines.append(f"[function_response] {function_response.name} -> {dict(function_response.response)}")
    return "\n".join(lines)

def estimate_tokens(history: list[types.Content]) -> int:
    return len(history_to_text(history)) // 4

def microcompact(history: list[types.Content]):
    function_responses = []
    for message_idx, content in enumerate(history):
        if content.role != "user" or not content.parts:
            continue
        for part_idx, part in enumerate(content.parts):
            if hasattr(part, "function_response") and part.function_response:
                function_responses.append((message_idx, part_idx, part.function_response.name))

    if len(function_responses) <= 3:
        return

    for message_idx, part_idx, tool_name in function_responses[:-3]:
        content = history[message_idx]
        part = content.parts[part_idx]
        if not (hasattr(part, "function_response") and part.function_response):
            continue
        payload = dict(part.function_response.response)
        output = str(payload.get("output", ""))
        if len(output) > 100:
            content.parts[part_idx] = types.Part.from_function_response(
                name=tool_name,
                response={"output": "[cleared]"},
            )

def auto_compact(client, history: list[types.Content]) -> list[types.Content]:
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(path, "w") as file_obj:
        for content in history:
            file_obj.write(json.dumps(content.model_dump(mode="json"), default=str) + "\n")

    conv_text = history_to_text(history)[:80000]
    resp = client.models.generate_content(
        model=MODEL_ID,
        contents=[
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=f"Summarize for continuity:\n{conv_text}")],
            )
        ],
    )
    summary = content_to_text(resp.candidates[0].content) or "(summary unavailable)"

    return [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"[Compressed. Transcript: {path}]\n{summary}")],
        ),
        types.Content(
            role="model",
            parts=[types.Part.from_text(text="Understood. Continuing with summary context.")],
        ),
    ]
