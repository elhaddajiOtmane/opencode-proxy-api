import json
import uuid
import time
import traceback
import requests
import os
import secrets
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from kiro_api import KiroAPI, KiroStreamError
import uvicorn

app = FastAPI()

# ── Dynamic Kiro Auth ────────────────────────────────────────────────────────
DASHBOARD_URL = "http://localhost:3128/api/active-profile"
DEFAULT_OPENAI_MODEL = os.environ.get("OPENAI_MODEL_NAME", "claude-sonnet-4.5")
DEFAULT_KIRO_MODEL = os.environ.get("KIRO_MODEL_ID", DEFAULT_OPENAI_MODEL)

# Expose additional models to opencode if configured as a comma-separated list
ADDITIONAL_OPENAI_MODELS = [
    m.strip()
    for m in os.environ.get("ADDITIONAL_OPENAI_MODELS", "").split(",")
    if m.strip()
]

OPENAI_MODELS = [DEFAULT_OPENAI_MODEL] + [m for m in ADDITIONAL_OPENAI_MODELS if m != DEFAULT_OPENAI_MODEL]

def get_machine_id():
    """Get or generate a persistent machine ID"""
    machine_id_file = "machine_id.txt"
    if os.path.exists(machine_id_file):
        try:
            with open(machine_id_file, "r") as f:
                return f.read().strip()
        except Exception as e:
            print(f"[PROXY] Warning: Could not read {machine_id_file}: {e}")
    
    new_id = secrets.token_hex(32)
    try:
        with open(machine_id_file, "w") as f:
            f.write(new_id)
    except Exception as e:
        print(f"[PROXY] Warning: Could not save machine ID: {e}")
    return new_id

MACHINE_ID = get_machine_id()

def get_active_kiro_api():
    """Fetch the active profile from the dashboard and return a KiroAPI instance"""
    try:
        resp = requests.get(DASHBOARD_URL, timeout=5)
        if resp.ok:
            data = resp.json()
            return KiroAPI(
                auth_token=data["access_token"],
                machine_id=MACHINE_ID,
                profile_arn=data["profile_arn"]
            )
    except Exception as e:
        print(f"[PROXY] Warning: Could not fetch active profile from dashboard: {e}")
    
    # Fallback to local profiles.json if dashboard is down
    try:
        with open("profiles.json", "r") as f:
            db = json.load(f)
            active_id = db.get("active_profile_id")
            for p in db.get("profiles", []):
                if p["id"] == active_id:
                    return KiroAPI(
                        auth_token=p["access_token"],
                        machine_id=MACHINE_ID,
                        profile_arn=p["profile_arn"]
                    )
    except:
        pass
        
    print("[PROXY] ERROR: No active Kiro profile found!")
    return None

# ── Load Kiro Native Tools ───────────────────────────────────────────────────
# These are ALWAYS sent to the Kiro backend in vibe mode
try:
    with open("tools.json", "r", encoding="utf-8") as f:
        KIRO_NATIVE_TOOLS = json.load(f)
    print(f"[INIT] Loaded {len(KIRO_NATIVE_TOOLS)} native Kiro tools from tools.json")
except FileNotFoundError:
    KIRO_NATIVE_TOOLS = []
    print("[INIT] WARNING: tools.json not found! Kiro vibe mode may return empty responses.")


# ── Helpers ──────────────────────────────────────────────────────────────────

KIRO_SYSTEM_PREAMBLE = """You are Kiro, an AI coding assistant. You help users with coding tasks. You can read files, write files, search code, and run commands. Always be helpful and concise."""


def stringify_message_content(content):
    """Normalize OpenAI message content into a plain string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "input_text":
                    parts.append(item.get("text", ""))
                else:
                    # Skip non-text content parts that Kiro cannot consume here.
                    continue
        return "\n".join(part for part in parts if part)
    return str(content)


def convert_anthropic_messages(messages, system_prompt, model_id):
    history = []
    
    # 1. Inject system prompt first
    full_system = (system_prompt or "").strip() or KIRO_SYSTEM_PREAMBLE
    history.append({
        "userInputMessage": {
            "content": full_system,
            "modelId": model_id,
            "origin": "AI_EDITOR"
        }
    })
    history.append({
        "assistantResponseMessage": {
            "content": "I will follow these instructions.",
            "toolUses": []
        }
    })
    
    # 2. Iterate and convert messages
    non_system_messages = [m for m in messages if m.get("role") != "system"]
    
    # Helper to extract text contents from Anthropic message content structure
    def extract_text_and_tools(content):
        text_parts = []
        tool_uses = []
        tool_results = []
        
        if isinstance(content, str):
            return content, tool_uses, tool_results
            
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                b_type = block.get("type")
                if b_type == "text":
                    text_parts.append(block.get("text", ""))
                elif b_type == "tool_use":
                    tool_uses.append({
                        "toolUseId": block.get("id", ""),
                        "name": block.get("name", ""),
                        "input": block.get("input", {})
                    })
                elif b_type == "tool_result":
                    tool_results.append({
                        "toolUseId": block.get("tool_use_id", ""),
                        "content": [{"text": block.get("content", "")}],
                        "status": "success"
                    })
                    
        return "\n\n".join(t for t in text_parts if t), tool_uses, tool_results

    # Group into alternating turns
    blocks = []
    for msg in non_system_messages:
        role = msg.get("role")
        # Map Anthropic role
        kiro_role = "assistant" if role == "assistant" else "user"
        if not blocks or blocks[-1]["role"] != kiro_role:
            blocks.append({"role": kiro_role, "messages": []})
        blocks[-1]["messages"].append(msg)
        
    # Convert all but the last block to history
    for block in blocks[:-1]:
        if block["role"] == "user":
            content_parts = []
            all_tool_results = []
            for msg in block["messages"]:
                text, _, t_results = extract_text_and_tools(msg.get("content"))
                if text:
                    content_parts.append(text)
                for tr in t_results:
                    all_tool_results.append(tr)
                    # Append as text reference too
                    content_parts.append(f"Tool result for {tr['toolUseId']}:\n{tr['content'][0]['text']}")
            
            user_msg = {
                "content": "\n\n".join(content_parts),
                "modelId": model_id,
                "origin": "AI_EDITOR"
              }
            if all_tool_results:
                user_msg["userInputMessageContext"] = {"toolResults": all_tool_results}
            history.append({"userInputMessage": user_msg})
        else:
            content_parts = []
            all_tool_uses = []
            for msg in block["messages"]:
                text, t_uses, _ = extract_text_and_tools(msg.get("content"))
                if text:
                    content_parts.append(text)
                for tu in t_uses:
                    all_tool_uses.append(tu)
            
            ast_msg = {
                "content": "\n\n".join(content_parts),
                "toolUses": all_tool_uses
            }
            history.append({"assistantResponseMessage": ast_msg})
            
    # Parse last block
    current_content = ""
    current_tool_results = []
    if blocks:
        last_block = blocks[-1]
        if last_block["role"] == "user":
            content_parts = []
            for msg in last_block["messages"]:
                text, _, t_results = extract_text_and_tools(msg.get("content"))
                if text:
                    content_parts.append(text)
                for tr in t_results:
                    current_tool_results.append(tr)
                    content_parts.append(f"Tool result for {tr['toolUseId']}:\n{tr['content'][0]['text']}")
            current_content = "\n\n".join(content_parts)
            
    return history, current_content, current_tool_results


def convert_anthropic_tools(anthropic_tools):
    kiro_tools = []
    for tool in anthropic_tools:
        kiro_tools.append({
            "toolSpecification": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "inputSchema": {
                    "json": tool.get("input_schema", {"type": "object", "properties": {}})
                }
            }
        })
    return kiro_tools


def convert_messages(messages, model_id):
    history = []
    
    # 1. Collect system prompt
    system_prompt = "\n\n".join([
        stringify_message_content(m.get("content", ""))
        for m in messages
        if m.get("role") == "system"
    ])
    full_system = (system_prompt.strip() or KIRO_SYSTEM_PREAMBLE)
    
    # Inject system prompt as first history pair (Kiro pattern)
    history.append({
        "userInputMessage": {
            "content": full_system,
            "modelId": model_id,
            "origin": "AI_EDITOR"
        }
    })
    history.append({
        "assistantResponseMessage": {
            "content": "I will follow these instructions.",
            "toolUses": []
        }
    })

    # 2. Group non-system messages into alternating User/Assistant blocks
    # "tool" messages are treated as "user" inputs containing toolResults
    non_system_messages = [m for m in messages if m.get("role") != "system"]
    
    blocks = []
    for msg in non_system_messages:
        role = msg.get("role")
        kiro_role = "assistant" if role == "assistant" else "user"
        
        if not blocks or blocks[-1]["role"] != kiro_role:
            blocks.append({"role": kiro_role, "messages": []})
            
        blocks[-1]["messages"].append(msg)
        
    # 3. Convert all but the last block into history
    for block in blocks[:-1]:
        if block["role"] == "user":
            content_parts = []
            tool_results = []
            
            for msg in block["messages"]:
                if msg.get("role") == "user":
                    content_parts.append(stringify_message_content(msg.get("content", "")))
                elif msg.get("role") == "tool":
                    tc_id = msg.get("tool_call_id", "unknown")
                    tc_content = stringify_message_content(msg.get("content", ""))
                    content_parts.append(f"Tool result for {tc_id}:\n{tc_content}")
                    tool_results.append({
                        "content": [{"text": tc_content}],
                        "status": "success",
                        "toolUseId": tc_id
                    })
            
            user_msg = {
                "content": "\n\n".join(content_parts),
                "modelId": model_id,
                "origin": "AI_EDITOR"
            }
            if tool_results:
                user_msg["userInputMessageContext"] = {"toolResults": tool_results}
                
            history.append({"userInputMessage": user_msg})
            
        else: # assistant
            content_parts = []
            tool_uses = []
            
            for msg in block["messages"]:
                content_parts.append(stringify_message_content(msg.get("content") or ""))
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        tool_uses.append({
                            "toolUseId": tc.get("id", ""),
                            "name": tc["function"]["name"],
                            "input": json.loads(tc["function"].get("arguments", "{}"))
                        })
            
            ast_msg = {
                "content": "\n\n".join(content_parts)
            }
            if tool_uses:
                ast_msg["toolUses"] = tool_uses
                
            history.append({"assistantResponseMessage": ast_msg})
            
    # 4. Handle the final block as the "currentMessage"
    current_content = ""
    current_tool_results = []
    
    if blocks:
        last_block = blocks[-1]
        if last_block["role"] == "user":
            content_parts = []
            for msg in last_block["messages"]:
                if msg.get("role") == "user":
                    content_parts.append(stringify_message_content(msg.get("content", "")))
                elif msg.get("role") == "tool":
                    tc_id = msg.get("tool_call_id", "unknown")
                    tc_content = stringify_message_content(msg.get("content", ""))
                    content_parts.append(f"Tool result for {tc_id}:\n{tc_content}")
                    current_tool_results.append({
                        "content": [{"text": tc_content}],
                        "status": "success",
                        "toolUseId": tc_id
                    })
            current_content = "\n\n".join(content_parts)
            
        else:
            # If the last message was from assistant, we append it to history 
            # and provide a dummy prompt to keep Kiro moving.
            content_parts = []
            tool_uses = []
            for msg in last_block["messages"]:
                content_parts.append(stringify_message_content(msg.get("content") or ""))
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        tool_uses.append({
                            "toolUseId": tc.get("id", ""),
                            "name": tc["function"]["name"],
                            "input": json.loads(tc["function"].get("arguments", "{}"))
                        })
            ast_msg = {"content": "\n\n".join(content_parts)}
            if tool_uses:
                ast_msg["toolUses"] = tool_uses
            history.append({"assistantResponseMessage": ast_msg})
            
            current_content = "Please continue."

    return history, current_content, current_tool_results


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": DEFAULT_OPENAI_MODEL,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "kiro"
            }
        ]
    }


def convert_tools(openai_tools):
    """Convert OpenAI tool schemas into AWS Kiro toolSpec schemas."""
    kiro_tools = []
    for tool in openai_tools:
        if tool.get("type") == "function":
            func = tool.get("function", {})
            kiro_tools.append({
                "toolSpecification": {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "inputSchema": {
                        "json": func.get("parameters", {"type": "object", "properties": {}})
                    }
                }
            })
    return kiro_tools


@app.post("/v1/messages")
async def anthropic_messages(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"type": "invalid_request_error", "message": "Invalid JSON body"}})

    messages = data.get("messages", [])
    system_prompt = data.get("system", "")
    model = data.get("model", "")
    stream = data.get("stream", False)
    anthropic_tools = data.get("tools", [])

    # Map Anthropic Model ID to Kiro Backend Model ID
    MODEL_MAP = {
        "claude-3-5-sonnet-20241022": "claude-sonnet-4.6",
        "claude-3-5-sonnet-latest":   "claude-sonnet-4.6",
        "claude-3-5-sonnet":          "claude-sonnet-4.6",
        "claude-3-opus-20240229":     "claude-opus-4.8",
        "claude-3-opus-latest":       "claude-opus-4.8",
        "claude-3-opus":              "claude-opus-4.8",
    }
    backend_model = MODEL_MAP.get(model, DEFAULT_OPENAI_MODEL)

    history, current_content, current_tool_results = convert_anthropic_messages(messages, system_prompt, backend_model)
    kiro_tools = convert_anthropic_tools(anthropic_tools) if anthropic_tools else KIRO_NATIVE_TOOLS

    conversation_id = str(uuid.uuid4())
    continuation_id = str(uuid.uuid4())

    api = get_active_kiro_api()
    if not api:
        return JSONResponse(
            status_code=502, 
            content={"error": {"type": "api_error", "message": "No active Kiro profile. Please activate one on the dashboard (port 3128)."}}
        )

    kiro_response = api.generate_assistant_response(
        content=current_content,
        conversation_id=conversation_id,
        agent_continuation_id=continuation_id,
        history=history,
        model_id=backend_model,
        agent_task_type="vibe",
        agent_mode="vibe",
        tools=kiro_tools,
        tool_results=current_tool_results,
        stream=True
    )

    if stream:
        return StreamingResponse(_stream_anthropic_sse(api, kiro_response, model), media_type="text/event-stream")
    else:
        return _non_stream_anthropic_response(api, kiro_response, model)


def _stream_anthropic_sse(api, kiro_response, model):
    msg_id = "msg_" + str(uuid.uuid4())
    first_chunk = True
    
    active_tools = {}
    
    try:
        # 1. Send message_start event
        msg_start = {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0}
            }
        }
        yield f"event: message_start\ndata: {json.dumps(msg_start)}\n\n"
        
        # 2. Iterate binary event stream
        for event in api.parse_stream(kiro_response, debug=True):
            
            # Text block handling
            if "content" in event and event.get("content"):
                text_val = event["content"]
                
                if first_chunk:
                    # Start text content block
                    yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                    first_chunk = False
                    
                delta = {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "text_delta",
                        "text": text_val
                    }
                }
                yield f"event: content_block_delta\ndata: {json.dumps(delta)}\n\n"
                
            # Tool use handling
            elif "toolUseId" in event:
                tool_id = event["toolUseId"]
                
                # Check if tool is not yet registered
                if tool_id not in active_tools:
                    idx = len(active_tools)
                    active_tools[tool_id] = {
                        "index": idx,
                        "name": event.get("name", ""),
                        "partial_json": ""
                    }
                    
                    tool_start = {
                        "type": "content_block_start",
                        "index": idx,
                        "content_block": {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": event.get("name", ""),
                            "input": {}
                        }
                    }
                    yield f"event: content_block_start\ndata: {json.dumps(tool_start)}\n\n"
                    
                tool_info = active_tools[tool_id]
                idx = tool_info["index"]
                
                # Stream the arguments
                if "input" in event:
                    arg_delta = str(event["input"])
                    tool_info["partial_json"] += arg_delta
                    
                    delta = {
                        "type": "content_block_delta",
                        "index": idx,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": arg_delta
                        }
                    }
                    yield f"event: content_block_delta\ndata: {json.dumps(delta)}\n\n"
                    
        # 3. Send stop for any active content blocks
        if not first_chunk:
            yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
            
        for tool_id, info in active_tools.items():
            yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': info['index']})}\n\n"
            
        # 4. Message delta & stop
        stop_reason = "tool_use" if active_tools else "end_turn"
        msg_delta = {
            "type": "message_delta",
            "delta": {
                "stop_reason": stop_reason,
                "stop_sequence": None
            },
            "usage": {"output_tokens": 0}
        }
        yield f"event: message_delta\ndata: {json.dumps(msg_delta)}\n\n"
        yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
        
    except Exception as e:
        err_payload = {"type": "error", "error": {"type": "api_error", "message": f"Kiro stream error: {e}"}}
        yield f"event: error\ndata: {json.dumps(err_payload)}\n\n"


def _non_stream_anthropic_response(api, kiro_response, model):
    content_blocks = []
    text_accumulator = []
    tool_uses = {}
    
    try:
        for event in api.parse_stream(kiro_response):
            if "content" in event and event.get("content"):
                text_accumulator.append(event["content"])
            elif "toolUseId" in event:
                tool_id = event["toolUseId"]
                if tool_id not in tool_uses:
                    tool_uses[tool_id] = {
                        "name": event.get("name", ""),
                        "partial_json": ""
                    }
                if "input" in event:
                    tool_uses[tool_id]["partial_json"] += str(event["input"])
                    
        # Build final response block
        if text_accumulator:
            content_blocks.append({
                "type": "text",
                "text": "".join(text_accumulator)
            })
            
        for tool_id, info in tool_uses.items():
            try:
                parsed_input = json.loads(info["partial_json"])
            except Exception:
                parsed_input = {}
            content_blocks.append({
                "type": "tool_use",
                "id": tool_id,
                "name": info["name"],
                "input": parsed_input
            })
            
        stop_reason = "tool_use" if tool_uses else "end_turn"
        
        return JSONResponse(content={
            "id": "msg_" + str(uuid.uuid4()),
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content_blocks,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0
            }
        })
        
    except Exception as e:
        return JSONResponse(
            status_code=502, 
            content={"error": {"type": "api_error", "message": f"Kiro stream error: {e}"}}
        )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})

    messages = data.get("messages", [])
    model = data.get("model", DEFAULT_OPENAI_MODEL)
    # Map requested model ID → Kiro backend model ID (Kiro uses dot notation)
    MODEL_MAP = {
        "claude-opus-4.8":    "claude-opus-4.8",
        "claude-opus-4-8":    "claude-opus-4.8",
        "claude-opus-4.5":    "claude-opus-4.5",
        "claude-opus-4-5":    "claude-opus-4.5",
        "claude-sonnet-4.6":  "claude-sonnet-4.6",
        "claude-sonnet-4-6":  "claude-sonnet-4.6",
        "claude-sonnet-4.5":  "claude-sonnet-4.5",
        "claude-sonnet-4-5":  "claude-sonnet-4.5",
    }
    backend_model = MODEL_MAP.get(model, model)  # Forward requested model, fallback to as-is
    stream = data.get("stream", False)
    openai_tools = data.get("tools", [])

    print(f"\n{'='*60}")
    print(f"[PROXY] Incoming  stream={stream}  messages={len(messages)} tools={len(openai_tools)}")
    for m in messages:
        role = m.get("role")
        content = stringify_message_content(m.get("content") or "")[:80]
        extra = ""
        if m.get("tool_calls"):
            extra = f" [+{len(m['tool_calls'])} tool_calls]"
        if m.get("tool_call_id"):
            extra = f" [tool_result for {m['tool_call_id']}]"
        print(f"  [{role}] {content}{extra}")
    print(f"{'='*60}")

    history, current_content, current_tool_results = convert_messages(messages, backend_model)
    
    # Translate OpenAI tools to Kiro tools
    kiro_tools = convert_tools(openai_tools) if openai_tools else KIRO_NATIVE_TOOLS

    conversation_id = str(uuid.uuid4())
    continuation_id = str(uuid.uuid4())

    # Fetch dynamic API instance
    api = get_active_kiro_api()
    if not api:
        return JSONResponse(status_code=500, content={"error": "No active Kiro profile. Please activate one on the dashboard (port 3128)."})

    kiro_response = api.generate_assistant_response(
        content=current_content,
        conversation_id=conversation_id,
        agent_continuation_id=continuation_id,
        history=history,
        model_id=backend_model,
        agent_task_type="vibe",
        agent_mode="vibe",
        tools=kiro_tools,
        tool_results=current_tool_results,
        stream=True
    )

    print(f"[PROXY] Kiro response status: {kiro_response.status_code}")
    print(f"[PROXY] Kiro response headers: {dict(kiro_response.headers)}", flush=True)

    if stream:
        return StreamingResponse(_stream_sse(api, kiro_response, model), media_type="text/event-stream")
    else:
        try:
            return _non_stream_response(api, kiro_response, model)
        except KiroStreamError as e:
            return JSONResponse(
                status_code=e.status_code or 502,
                content={
                    "error": {
                        "message": str(e),
                        "type": e.payload.get("reason", "kiro_backend_error") if e.payload else "kiro_backend_error",
                        "details": e.payload,
                    }
                },
            )


def _stream_sse(api, kiro_response, model):
    """Generator yielding proper OpenAI SSE chunks from the Kiro binary stream."""
    resp_id = "chatcmpl-" + str(uuid.uuid4())
    created = int(time.time())
    first_chunk = True
    has_tool_calls = False
    
    active_tools = {}
    next_tool_index = 0
    event_count = 0

    try:
        for event in api.parse_stream(kiro_response, debug=True):
            event_count += 1

            # ── Text content ─────────────────────────────────────────
            if "content" in event and event.get("content"):
                delta = {"content": event["content"]}
                if first_chunk:
                    delta["role"] = "assistant"
                    first_chunk = False

                chunk = {
                    "id": resp_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": delta,
                        "finish_reason": None
                    }]
                }
                print(f"[SSE] text: {event['content'][:60]}", flush=True)
                yield f"data: {json.dumps(chunk)}\n\n"

            # ── Tool calls ───────────────────────────────────────────
            elif "toolUseId" in event:
                has_tool_calls = True
                tool_call_id = event["toolUseId"]
                
                if tool_call_id not in active_tools:
                    active_tools[tool_call_id] = next_tool_index
                    next_tool_index += 1
                
                idx = active_tools[tool_call_id]

                delta = {}
                if first_chunk:
                    delta["role"] = "assistant"
                    delta["content"] = None
                    first_chunk = False

                tool_delta = {
                    "index": idx
                }
                
                # First chunk of a tool call includes id, type, and name
                if "name" in event and "input" not in event:
                    tool_delta["id"] = tool_call_id
                    tool_delta["type"] = "function"
                    tool_delta["function"] = {"name": event["name"], "arguments": ""}
                
                # Subsequent chunks stream the arguments
                if "input" in event:
                    if "function" not in tool_delta:
                        tool_delta["function"] = {}
                    tool_delta["function"]["arguments"] = str(event["input"])

                delta["tool_calls"] = [tool_delta]

                chunk = {
                    "id": resp_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": delta,
                        "finish_reason": None
                    }]
                }
                print(f"[SSE] tool_call chunk: idx={idx} id={tool_call_id}", flush=True)
                yield f"data: {json.dumps(chunk)}\n\n"

            else:
                # Log other event types (metering, context usage, etc.) but don't forward
                print(f"[SSE] skip event: {list(event.keys())}", flush=True)

        # ── Final chunk with finish_reason ────────────────────────────
        finish_reason = "tool_calls" if has_tool_calls else "stop"

        # If we never sent any chunk, send an empty assistant message so Opencode doesn't hang
        if first_chunk:
            empty_chunk = {
                "id": resp_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": ""},
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(empty_chunk)}\n\n"

        final_chunk = {
            "id": resp_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": finish_reason
            }]
        }
        print(f"[SSE] finish_reason={finish_reason}  total_events={event_count}", flush=True)
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    except KiroStreamError as e:
        print(f"[SSE ERROR] {e}")
        err_chunk = {
            "id": resp_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": f"\n\n[Proxy Error: {e}]"},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(err_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        print(f"[SSE ERROR] {e}")
        traceback.print_exc()
        err_chunk = {
            "id": resp_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": f"\n\n[Proxy Error: {e}]"},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(err_chunk)}\n\n"
        yield "data: [DONE]\n\n"


def _non_stream_response(api, kiro_response, model):
    """Collects the full Kiro stream into a single OpenAI-format JSON response."""
    full_content = ""
    tool_calls_dict = {}

    for event in api.parse_stream(kiro_response):
        if "content" in event and event.get("content"):
            full_content += event["content"]
        elif "toolUseId" in event:
            tid = event["toolUseId"]
            if tid not in tool_calls_dict:
                tool_calls_dict[tid] = {
                    "id": tid,
                    "type": "function",
                    "function": {"name": event.get("name", "unknown_tool"), "arguments": ""}
                }
            if "input" in event:
                tool_calls_dict[tid]["function"]["arguments"] += str(event["input"])

    message = {"role": "assistant", "content": full_content}
    finish_reason = "stop"

    tool_calls = list(tool_calls_dict.values())
    if tool_calls:
        message["tool_calls"] = tool_calls
        finish_reason = "tool_calls"

    return JSONResponse(content={
        "id": "chatcmpl-" + str(uuid.uuid4()),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    })


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Kiro -> OpenAI Proxy on http://127.0.0.1:8000")
    print(f"  Native tools loaded: {len(KIRO_NATIVE_TOOLS)}")
    print("  Endpoints:")
    print("    GET  /v1/models")
    print("    POST /v1/chat/completions")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8000)
