import asyncio
import json
import logging
import time
import base64
import tempfile
import os
import uuid
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal, get_db
from app.dependencies.auth import get_current_user, get_current_user_ws
from app.models.users import User
from app.graphs.rxresume import to_rxresume
from app.graphs.state import new_resume
from app.services.chat_service import (
    add_message,
    ensure_session,
    get_messages,
    list_sessions,
    owns_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])

from collections import defaultdict

                                           
ACTIVE_CONNECTIONS: dict[str, set[WebSocket]] = defaultdict(set)
MAX_MESSAGE_SIZE = 10 * 1024 * 1024         


@router.get("/sessions/{session_id}/resume.json")
async def export_resume(
    session_id: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """The profile as a Reactive Resume v5.0.0 document, ready for any portal that
    speaks the schema. Returns the tailored version when one exists."""
    if not await owns_session(db, session_id, current_user.id):
        raise HTTPException(status_code=404, detail="Session not found")

    state = (await request.app.state.graph.aget_state(
        {"configurable": {"thread_id": session_id}}
    )).values or {}

    resume = (state.get("generated_resumes") or {}).get("tailored") or state.get("master_profile")
    if not resume:
        raise HTTPException(status_code=404, detail="This session has no resume yet")

    return to_rxresume(resume)


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

                                       
    current_llm_task: asyncio.Task | None = None

    try:
        while True:
                                                    
            if time.time() > token_exp:
                logger.warning("Token expired for user %s mid-connection", current_user.id)
                await websocket.send_json({"type": "error", "code": 4401, "reason": "token_expired"})
                await websocket.close(code=4401, reason="Token expired")
                break

                                 
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

            elif msg_type == "list_sessions":
                async with AsyncSessionLocal() as db:
                    await websocket.send_json({
                        "type": "sessions",
                        "sessions": await list_sessions(db, current_user.id),
                    })
                continue

            elif msg_type == "history":
                                                                                  
                                                                           
                session_id = payload.get("session_id")
                if not session_id:
                    await websocket.send_json({"type": "error", "reason": "Missing session_id"})
                    continue

                async with AsyncSessionLocal() as db:
                    messages = await get_messages(db, session_id, current_user.id)

                if messages is None:
                    await websocket.send_json({"type": "error", "reason": "Session not found"})
                    continue

                state = (await websocket.app.state.graph.aget_state(
                    {"configurable": {"thread_id": session_id}}
                )).values or {}
                profile = state.get("master_profile")

                await websocket.send_json({
                    "type": "history",
                    "session_id": session_id,
                    "messages": messages,
                    "current_question": state.get("current_question"),
                    "completion": state.get("completion", 0),
                    "phase": state.get("phase"),
                    "pdf_path": state.get("pdf_path"),
                    "ats_score": state.get("ats_score"),
                    "master_profile": profile.model_dump() if hasattr(profile, "model_dump") else profile,
                })
                continue

            elif msg_type == "message":
                query = payload.get("content")
                if not query:
                    await websocket.send_json({"type": "error", "reason": "Missing content"})
                    continue

                session_id = payload.get("session_id") or str(uuid4())

                                               
                if current_llm_task and not current_llm_task.done():
                    current_llm_task.cancel()

                                                                   
                current_llm_task = asyncio.create_task(
                    run_and_stream_graph(websocket, None, None, "", session_id, current_user.id, answer=query)
                )

            elif msg_type == "create_scratch":
                data = payload.get("data", {})
                session_id = payload.get("session_id") or str(uuid4())

                                               
                if current_llm_task and not current_llm_task.done():
                    current_llm_task.cancel()

                current_llm_task = asyncio.create_task(
                    run_and_stream_graph(websocket, None, None, "", session_id, current_user.id, scratch_data=data)
                )

            elif msg_type == "upload":
                uploaded_text = payload.get("text")
                file_data = payload.get("file_data")
                file_name = payload.get("file_name", "upload.pdf")
                
                if not uploaded_text and not file_data:
                    await websocket.send_json({"type": "error", "reason": "Missing uploaded text or file data"})
                    continue
                
                session_id = payload.get("session_id") or str(uuid4())
                
                                               
                if current_llm_task and not current_llm_task.done():
                    current_llm_task.cancel()

                current_llm_task = asyncio.create_task(
                    run_and_stream_graph(websocket, uploaded_text, file_data, file_name, session_id, current_user.id)
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


def _new_state(session_id: str, user_id: uuid.UUID, **overrides) -> dict:
    """A fresh graph state. Overrides are for whatever kicked the session off."""
    state = {
        "session_id": session_id,
        "user_id": str(user_id),
        "master_profile": new_resume(),
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
        "current_question": None,
    }
    state.update(overrides)
    return state


def _completion_message(pdf_path: str, ats: dict) -> str:
    msg = f"Your resume is ready! [Download PDF]({pdf_path})"
    if not ats:
        return msg
    msg += f"\n\n**ATS match: {ats['score']}/100**"
    if ats.get("missing_keywords"):
        msg += f"\n\nStill missing from your resume: {', '.join(ats['missing_keywords'][:5])}"
    if ats.get("feedback"):
        msg += f"\n\n{ats['feedback']}"
    return msg


async def run_and_stream_graph(websocket: WebSocket, uploaded_text: str | None, file_data: str | None, file_name: str, session_id: str, user_id: uuid.UUID, answer: str = None, scratch_data: dict = None):
    graph = websocket.app.state.graph
    uploaded_file_path = None
    config = {"configurable": {"thread_id": session_id}}

                                                     
    if answer:
        opening = answer
    elif file_data:
        opening = f"Uploaded {file_name}"
    elif uploaded_text:
        opening = "Pasted my resume text"
    else:
        opening = "Started a new resume"

    try:
        async with AsyncSessionLocal() as db:
                                                                                        
            if not await ensure_session(db, session_id, user_id, opening):
                logger.warning("User %s tried to open session %s owned by someone else", user_id, session_id)
                await websocket.send_json({"type": "error", "reason": "Session not found"})
                return

            existing = (await graph.aget_state(config)).values or {}
            await add_message(db, session_id, "user", opening)

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
                input_state = _new_state(session_id, user_id, master_profile=resume)
            elif answer and not existing:
                                                                                         
                input_state = _new_state(
                    session_id, user_id,
                    uploaded_text=answer,
                    latest_answer=answer,
                )
            elif answer:
                input_state = {"latest_answer": answer}
            else:
                input_state = _new_state(
                    session_id, user_id,
                    uploaded_text=uploaded_text,
                    uploaded_file=uploaded_file_path,
                )

            ats: dict = {}

                               
            async for output in graph.astream(input_state, config, stream_mode="updates"):
                                                                  
                for node, state_updates in output.items():
                    logger.info("Graph update from node %s", node)

                                                                              
                                                                    
                    if "master_profile" in state_updates and hasattr(state_updates["master_profile"], "model_dump"):
                        state_updates["master_profile"] = state_updates["master_profile"].model_dump()
                    if "generated_resumes" in state_updates:
                        for key, val in state_updates["generated_resumes"].items():
                            if hasattr(val, "model_dump"):
                                state_updates["generated_resumes"][key] = val.model_dump()

                    if "ats_score" in state_updates:
                        ats = {"score": state_updates["ats_score"], **(state_updates.get("ats_feedback") or {})}

                    await websocket.send_json({
                        "type": "graph_update",
                        "node": node,
                        "data": state_updates
                    })

                                                                                          
                                                                                   
                    question = state_updates.get("current_question")
                    if question and question.get("question_text"):
                        await add_message(
                            db, session_id, "assistant",
                            question["question_text"],
                            question.get("ui"),
                            question.get("options"),
                        )

                    if node == "parse_document" and not state_updates.get("master_profile"):
                        notice = "I couldn't read that file, so I'll ask you for the details instead."
                        await add_message(db, session_id, "assistant", notice)
                        await websocket.send_json({"type": "notice", "reason": notice})

                    if state_updates.get("phase") == "completed" and state_updates.get("pdf_path"):
                        done_card = {
                            "field": "system",
                            "question_text": _completion_message(state_updates["pdf_path"], ats),
                            "ui": "chips",
                            "options": ["Tailor for another job"],
                        }
                        await add_message(
                            db, session_id, "assistant",
                            done_card["question_text"], done_card["ui"], done_card["options"],
                        )
                        await websocket.send_json({
                            "type": "graph_update",
                            "node": "system",
                            "data": {"current_question": done_card},
                        })

            await websocket.send_json({
                "type": "done",
                "session_id": session_id,
            })
    except asyncio.CancelledError:
        await websocket.send_json({
            "type": "done",
            "session_id": session_id,
        })
    except Exception as e:
        logger.error("Error during graph execution: %r", e)
        await websocket.send_json({"type": "error", "reason": "Graph execution failed"})
    finally:
        if uploaded_file_path and os.path.exists(uploaded_file_path):
            os.remove(uploaded_file_path)