import asyncio
import json
import logging
import time
import base64
import tempfile
import os
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect

from app.dependencies.auth import get_current_user_ws
from app.models.users import User
from app.graphs.state import new_resume

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])

from collections import defaultdict

# Simple rate limit and connection tracking
ACTIVE_CONNECTIONS: dict[str, set[WebSocket]] = defaultdict(set)
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB


@router.websocket("/ws")
async def chat_endpoint(
    websocket: WebSocket,
    auth_data: Annotated[tuple[User, float] | tuple[None, None], Depends(get_current_user_ws)],
):
    current_user, token_exp = auth_data
    if current_user is None or token_exp is None:
        logger.warning("WebSocket connection rejected: auth failed")
        return

    try:
        await websocket.accept()
    except RuntimeError:
        return

    user_id_str = str(current_user.id)
    ACTIVE_CONNECTIONS[user_id_str].add(websocket)
    logger.info("WebSocket accepted for user %s. Total connections: %d", current_user.id, len(ACTIVE_CONNECTIONS[user_id_str]))

    # Get LLM singleton from app state
    llm = websocket.app.state.llm

    # Background task for LLM streaming
    current_llm_task: asyncio.Task | None = None

    try:
        while True:
            # Check token expiry before each receive
            if time.time() > token_exp:
                logger.warning("Token expired for user %s mid-connection", current_user.id)
                await websocket.send_json({"type": "error", "code": 4401, "reason": "token_expired"})
                await websocket.close(code=4401, reason="Token expired")
                break

            # Receive raw payload
            raw_text = await websocket.receive_text()
            if len(raw_text) > MAX_MESSAGE_SIZE:
                await websocket.send_json({"type": "error", "reason": "Message too large"})
                continue

            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "reason": "Invalid JSON"})
                continue

            msg_type = payload.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            elif msg_type == "cancel":
                if current_llm_task and not current_llm_task.done():
                    current_llm_task.cancel()
                    logger.info("Cancelled generation for user %s", current_user.id)
                continue

            elif msg_type == "message":
                query = payload.get("content")
                if not query:
                    await websocket.send_json({"type": "error", "reason": "Missing content"})
                    continue

                session_id = payload.get("session_id") or str(uuid4())
                message_id = str(uuid4())

                # Cancel any ongoing generation
                if current_llm_task and not current_llm_task.done():
                    current_llm_task.cancel()

                # Start new graph task to resume with latest answer
                current_llm_task = asyncio.create_task(
                    run_and_stream_graph(websocket, None, None, "", session_id, answer=query)
                )

            elif msg_type == "create_scratch":
                data = payload.get("data", {})
                session_id = payload.get("session_id") or str(uuid4())

                # Cancel any ongoing generation
                if current_llm_task and not current_llm_task.done():
                    current_llm_task.cancel()

                current_llm_task = asyncio.create_task(
                    run_and_stream_graph(websocket, None, None, "", session_id, scratch_data=data)
                )

            elif msg_type == "upload":
                uploaded_text = payload.get("text")
                file_data = payload.get("file_data")
                file_name = payload.get("file_name", "upload.pdf")
                
                if not uploaded_text and not file_data:
                    await websocket.send_json({"type": "error", "reason": "Missing uploaded text or file data"})
                    continue
                
                session_id = payload.get("session_id") or str(uuid4())
                
                # Cancel any ongoing generation
                if current_llm_task and not current_llm_task.done():
                    current_llm_task.cancel()

                current_llm_task = asyncio.create_task(
                    run_and_stream_graph(websocket, uploaded_text, file_data, file_name, session_id)
                )

            else:
                await websocket.send_json({"type": "error", "reason": f"Unknown type {msg_type}"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for user %s", current_user.id)
    except Exception as e:
        logger.error("Error in websocket chat for user %s: %r", current_user.id, e)
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except RuntimeError:
            pass
    finally:
        ACTIVE_CONNECTIONS[user_id_str].discard(websocket)
        if not ACTIVE_CONNECTIONS[user_id_str]:
            ACTIVE_CONNECTIONS.pop(user_id_str, None)
        if current_llm_task and not current_llm_task.done():
            current_llm_task.cancel()


async def stream_llm_response(websocket: WebSocket, llm, query: str, session_id: str, message_id: str):
    title = query[:50].strip()
    
    try:
        await websocket.send_json({
            "type": "metadata",
            "session_id": session_id,
            "message_id": message_id,
            "title": title,
        })

        async for chunk in llm.astream(query):
            if chunk.content:
                await websocket.send_json({
                    "type": "delta",
                    "message_id": message_id,
                    "data": chunk.content,
                })

        await websocket.send_json({
            "type": "done",
            "session_id": session_id,
            "message_id": message_id,
        })

    except asyncio.CancelledError:
        # Client requested cancellation
        await websocket.send_json({
            "type": "done",
            "session_id": session_id,
            "message_id": message_id,
        })
    except Exception as e:
        logger.error("Error during LLM stream: %r", e)
        await websocket.send_json({
            "type": "error",
            "message_id": message_id,
            "reason": "LLM generation failed",
        })

async def run_and_stream_graph(websocket: WebSocket, uploaded_text: str | None, file_data: str | None, file_name: str, session_id: str, answer: str = None, scratch_data: dict = None):
    graph = websocket.app.state.graph
    uploaded_file_path = None
    config = {"configurable": {"thread_id": session_id}}

    try:
        await websocket.send_json({
            "type": "metadata",
            "session_id": session_id,
            "title": "Starting Resume Architect..." if scratch_data else ("Processing..." if answer else "Parsing Resume..."),
        })
        
        if file_data:
            if "," in file_data:
                file_data = file_data.split(",", 1)[1]
            binary_data = base64.b64decode(file_data)
            
            fd, uploaded_file_path = tempfile.mkstemp(suffix=".pdf")
            with os.fdopen(fd, 'wb') as f:
                f.write(binary_data)
        
        if scratch_data is not None:
            resume = new_resume()
            resume.basics.name = scratch_data.get("name", "")
            resume.basics.email = scratch_data.get("email", "")
            resume.basics.phone = scratch_data.get("phone", "")
            resume.basics.location = scratch_data.get("location", "")
            input_state = {
                "session_id": session_id,
                "messages": [],
                "master_profile": resume,
                "generated_resumes": {},
                "resume_versions": [],
                "workflow_type": None,
                "workflow": None,
                "current_step": "Initializing",
                "completion": 0,
                "uploaded_text": None,
                "uploaded_file": None,
                "tasks": [],
                "extracted_entities": {},
                "validation_errors": [],
                "pending_verifications": [],
                "phase": "collecting",
                "skipped": [],
                "question_queue": [],
                "current_question": None
            }
        elif answer:
            current_state = await graph.aget_state(config)
            if not current_state.values:
                # First message in a brand new session
                input_state = {
                    "session_id": session_id,
                    "messages": [],
                    "master_profile": new_resume(),
                    "generated_resumes": {},
                "resume_versions": [],
                    "workflow_type": None,
                "workflow": None,
                "current_step": "Initializing",
                "completion": 0,
                    "uploaded_text": answer,
                    "uploaded_file": None,
                    "tasks": [],
                    "extracted_entities": {},
                    "validation_errors": [],
                "pending_verifications": [],
                    "phase": "collecting",
                    "skipped": [],
                    "question_queue": [],
                    "current_question": None,
                    "latest_answer": answer
                }
            else:
                input_state = {"latest_answer": answer}
        else:
            input_state = {
                "session_id": session_id,
                "messages": [],
                "master_profile": new_resume(),
                "generated_resumes": {},
                "resume_versions": [],
                "workflow_type": None,
                "workflow": None,
                "current_step": "Initializing",
                "completion": 0,
                "uploaded_text": uploaded_text,
                "uploaded_file": uploaded_file_path,
                "tasks": [],
                "extracted_entities": {},
                "validation_errors": [],
                "pending_verifications": [],
                "phase": "collecting",
                "skipped": [],
                "question_queue": [],
                "current_question": None
            }
        
        # Stream from graph
        async for output in graph.astream(input_state, config, stream_mode="updates"):
            # 'output' is a dict of {node_name: state_updates}
            for node, state_updates in output.items():
                logger.info("Graph update from node %s", node)
                
                # We need to make sure state_updates is JSON serializable. 
                # Pydantic models need to be converted to dicts.
                if "master_profile" in state_updates and hasattr(state_updates["master_profile"], "model_dump"):
                    state_updates["master_profile"] = state_updates["master_profile"].model_dump()
                if "generated_resumes" in state_updates:
                    for key, val in state_updates["generated_resumes"].items():
                        if hasattr(val, "model_dump"):
                            state_updates["generated_resumes"][key] = val.model_dump()
                
                await websocket.send_json({
                    "type": "graph_update",
                    "node": node,
                    "data": state_updates
                })

                if state_updates.get("phase") == "completed" and state_updates.get("pdf_path"):
                    await websocket.send_json({
                        "type": "graph_update",
                        "node": "system",
                        "data": {
                            "current_question": {
                                "field": "system",
                                "question_text": f"Your resume is ready! [Download PDF]({state_updates['pdf_path']})",
                                "ui": "text",
                                "options": []
                            }
                        }
                    })

        if uploaded_file_path and os.path.exists(uploaded_file_path):
            os.remove(uploaded_file_path)

        await websocket.send_json({
            "type": "done",
            "session_id": session_id,
        })
    except asyncio.CancelledError:
        if uploaded_file_path and os.path.exists(uploaded_file_path):
            os.remove(uploaded_file_path)
        await websocket.send_json({
            "type": "done",
            "session_id": session_id,
        })
    except Exception as e:
        logger.error("Error during graph execution: %r", e)
        if uploaded_file_path and os.path.exists(uploaded_file_path):
            os.remove(uploaded_file_path)
        await websocket.send_json({"type": "error", "reason": "Graph execution failed"})
