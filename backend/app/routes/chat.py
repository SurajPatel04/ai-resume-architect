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

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal, get_db
from app.dependencies.auth import get_current_user, get_current_user_ws
from app.models.users import User
from app.graphs.rxresume import to_rxresume
from app.graphs.state import new_resume
from app.utils.transcribe import TranscriptionError, transcribe
from app.services.chat_service import (
    add_message,
    ensure_session,
    get_messages,
    list_sessions,
    owns_session,
)

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langgraph.graph import START

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])

from collections import defaultdict

ACTIVE_CONNECTIONS: dict[str, set[WebSocket]] = defaultdict(set)
MAX_MESSAGE_SIZE = 10 * 1024 * 1024

UPLOAD_MAX_BYTES = 10 * 1024 * 1024
UPLOAD_CHUNK = 64 * 1024
PDF_MAGIC = b"%PDF-"

def _upload_dir(user_id: uuid.UUID) -> str:
    """Where a user's staged uploads live.

    Keyed by user, so an upload_id from one account can never resolve to another's
    file — the socket handler rebuilds this path from the *authenticated* user.

    ponytail: orphans (uploaded, never sent) are only reaped by the OS cleaning
    /tmp. Add a sweep here if these ever outlive a reboot.
    """
    return os.path.join(tempfile.gettempdir(), "resume-uploads", str(user_id))

def _staged_upload(user_id: uuid.UUID, upload_id: str) -> str | None:
    """Resolve a staged upload to a path, or None if it isn't there.

    Parsing upload_id as a UUID is what stops "../../etc/passwd" from becoming a path.
    """
    try:
        safe_id = str(uuid.UUID(str(upload_id)))
    except (ValueError, AttributeError, TypeError):
        return None

    path = os.path.join(_upload_dir(user_id), safe_id)
    return path if os.path.isfile(path) else None

@router.post("/upload")
async def upload_resume(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    file: Annotated[UploadFile, File()],
):
    """Stage a resume PDF, streamed to disk. Returns the id to send over the socket.

    Kept off the WebSocket so a multi-megabyte body can't sit in memory or block the
    chat channel's pings and cancels while it arrives.
    """

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="That file is larger than 10 MB.")

    upload_id = str(uuid4())
    directory = _upload_dir(current_user.id)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, upload_id)

    written = 0
    try:
        with open(path, "wb") as out:
            while chunk := await file.read(UPLOAD_CHUNK):

                if written == 0 and not chunk.startswith(PDF_MAGIC):
                    raise HTTPException(status_code=415, detail="Only PDF resumes are supported.")

                written += len(chunk)
                if written > UPLOAD_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="That file is larger than 10 MB.")

                out.write(chunk)

        if written == 0:
            raise HTTPException(status_code=400, detail="That file is empty.")
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise

    logger.info("Staged upload %s (%d bytes) for user %s", upload_id, written, current_user.id)
    return {"upload_id": upload_id, "file_name": file.filename or "resume.pdf"}

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
                    "ats_feedback": state.get("ats_feedback"),
                    "quality_score": state.get("quality_score"),
                    "quality_feedback": state.get("quality_feedback"),
                    "master_profile": profile.model_dump() if hasattr(profile, "model_dump") else profile,
                    "usage": state.get("usage") or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
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

            elif msg_type == "voice":
                                                                                 
                audio_data = payload.get("audio")
                if not audio_data:
                    await websocket.send_json({"type": "error", "reason": "Missing audio"})
                    continue

                if "," in audio_data:
                    audio_data = audio_data.split(",", 1)[1]

                try:
                    transcript = await transcribe(
                        base64.b64decode(audio_data),
                        payload.get("mimetype") or "audio/webm",
                    )
                except (TranscriptionError, ValueError) as e:
                    logger.error("Transcription failed for user %s: %r", current_user.id, e)
                    await websocket.send_json({
                        "type": "error",
                        "reason": "Couldn't transcribe that recording. Try again or type it instead.",
                    })
                    continue

                if not transcript:
                    await websocket.send_json({
                        "type": "error",
                        "reason": "I didn't catch anything in that recording.",
                    })
                    continue

                await websocket.send_json({"type": "transcript", "text": transcript})

                session_id = payload.get("session_id") or str(uuid4())

                if current_llm_task and not current_llm_task.done():
                    current_llm_task.cancel()

                current_llm_task = asyncio.create_task(
                    run_and_stream_graph(websocket, None, None, "", session_id, current_user.id, answer=transcript)
                )

            elif msg_type == "create_scratch":
                                                                                     
                data = {
                    "name": f"{current_user.first_name} {current_user.last_name}".strip(),
                    "email": current_user.email,
                }
                session_id = payload.get("session_id") or str(uuid4())

                if current_llm_task and not current_llm_task.done():
                    current_llm_task.cancel()

                current_llm_task = asyncio.create_task(
                    run_and_stream_graph(websocket, None, None, "", session_id, current_user.id, scratch_data=data)
                )

            elif msg_type == "upload":
                                                                                         
                uploaded_text = payload.get("text")
                upload_id = payload.get("upload_id")
                file_name = payload.get("file_name", "upload.pdf")
                logger.info("Received upload hand-off for %s", file_name)

                if not uploaded_text and not upload_id:
                    await websocket.send_json({"type": "error", "reason": "Missing uploaded text or upload_id"})
                    continue

                file_path = None
                if upload_id:
                    file_path = _staged_upload(current_user.id, upload_id)
                    if not file_path:
                        await websocket.send_json({
                            "type": "error",
                            "reason": "That upload is no longer available. Please attach the file again.",
                        })
                        continue

                session_id = payload.get("session_id") or str(uuid4())

                if current_llm_task and not current_llm_task.done():
                    current_llm_task.cancel()

                current_llm_task = asyncio.create_task(
                    run_and_stream_graph(websocket, uploaded_text, file_path, file_name, session_id, current_user.id)
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

def _spent_since(before: dict, after: dict) -> dict:
    """What was spent between two readings of the running total."""
    return {key: after.get(key, 0) - before.get(key, 0) for key in after}

def _print_node_usage(nodes: str, usage: dict) -> None:
    """One line per node as the graph walks it, so a surprise bill has a name on it.

    The handler on the graph config accumulates across every node, so a node's own spend
    is the difference between the total now and the total at the previous step. That is
    exact only while the graph runs one node at a time, which it does — every edge here
    picks a single target.

    ponytail: reads the accumulator instead of tagging calls per node. Add a handler per
    node if the graph ever fans out and these numbers start landing on the wrong name.
    """
    print(
        f"[node] {nodes:<22} "
        f"{usage['input_tokens']:>7} in + {usage['output_tokens']:>6} out "
        f"= {usage['total_tokens']:>7}",
        flush=True,
    )

def _turn_usage(handler: UsageMetadataCallbackHandler) -> dict:
    """Flatten the per-model breakdown the handler collects into one turn total.

    A single turn can touch several nodes and more than one model, and each of those
    is a separate key in `usage_metadata`.
    """
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for usage in (handler.usage_metadata or {}).values():
        totals["input_tokens"] += usage.get("input_tokens", 0)
        totals["output_tokens"] += usage.get("output_tokens", 0)
        totals["total_tokens"] += usage.get("total_tokens", 0)
    return totals

_usage_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

async def _bank_usage(graph, config: dict, session_id: str, turn: dict) -> dict:
    """Add one turn to the session total and return the new total.

    aupdate_state is not atomic across concurrent callers — two of them read the same
    base checkpoint and the second overwrites the first. A cancelled turn reports its
    spend while the replacing turn is already running, so that overlap is real.

    ponytail: single-process lock. Needs Redis or a SQL upsert if this ever runs
    behind more than one worker.
    """
    async with _usage_locks[session_id]:
                                                                                      
        await graph.aupdate_state(config, {"usage": turn}, as_node=START)
        return ((await graph.aget_state(config)).values or {}).get("usage") or turn

async def _report_usage(websocket: WebSocket, graph, config: dict, session_id: str, handler: UsageMetadataCallbackHandler) -> None:
    """Fold this turn's tokens into the session total, print it, and push it to the client.

    The running total lives in the checkpoint under `usage`, so it rides along with the
    rest of the session state instead of needing its own table.
    """
    turn = _turn_usage(handler)
    if not turn["total_tokens"]:
        return

    session_total = turn
    try:
        session_total = await _bank_usage(graph, config, session_id, turn)
    except Exception as e:
                                                                         
        logger.warning("Could not write usage into graph state: %r", e)

    print(
        f"[tokens] session={session_id} | "
        f"this turn: {turn['input_tokens']} in + {turn['output_tokens']} out = {turn['total_tokens']} | "
        f"conversation: {session_total['input_tokens']} in + {session_total['output_tokens']} out "
        f"= {session_total['total_tokens']}",
        flush=True,
    )

    await websocket.send_json({"type": "usage", "turn": turn, "session": session_total})

def _greeting(full_name: str) -> str:
    """How a from-scratch session opens, before the first question is put."""
    first = (full_name or "").split(" ")[0].strip()
    hello = f"Hi {first}, let's build your resume." if first else "Let's build your resume."
    return f"{hello} I'll ask a few short questions and fill it in as we go."

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

async def run_and_stream_graph(websocket: WebSocket, uploaded_text: str | None, uploaded_file_path: str | None, file_name: str, session_id: str, user_id: uuid.UUID, answer: str = None, scratch_data: dict = None):
    graph = websocket.app.state.graph

    usage_handler = UsageMetadataCallbackHandler()
    config = {"configurable": {"thread_id": session_id}, "callbacks": [usage_handler]}

    if answer:
        opening = answer
    elif uploaded_file_path:
        opening = f"Uploaded {file_name}"
    elif uploaded_text:
        opening = "Pasted my resume text"
    else:
        opening = "Started a new resume"

    try:
        logger.info("Starting graph session=%s source=%s", session_id,
                    "upload" if uploaded_file_path else ("text" if uploaded_text else "answer"))
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

            if scratch_data is not None:
                resume = new_resume()
                resume.basics.name = scratch_data.get("name", "")
                resume.basics.email = scratch_data.get("email", "")

                hello = _greeting(resume.basics.name)
                await add_message(db, session_id, "assistant", hello)
                await websocket.send_json({"type": "notice", "reason": hello})

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
                                                                                       
            banked = _turn_usage(usage_handler)

            async for output in graph.astream(input_state, config, stream_mode="updates"):
                                                                                     
                running = _turn_usage(usage_handler)
                _print_node_usage(", ".join(output), _spent_since(banked, running))
                banked = running

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

                    if state_updates.get("phase") == "completed":
                        pdf_path = state_updates.get("pdf_path")
                        if pdf_path:
                            text = _completion_message(pdf_path, ats)
                        else:
                                                                                    
                            text = (
                                f"Your resume is written, but {state_updates.get('render_error') or 'the PDF could not be generated'} "
                                "Your answers are saved — try again once that's sorted."
                            )

                        done_card = {
                            "field": "system",
                            "question_text": text,
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

            await _report_usage(websocket, graph, config, session_id, usage_handler)

            await websocket.send_json({
                "type": "done",
                "session_id": session_id,
            })
    except asyncio.CancelledError:
                                                                          
        await _report_usage(websocket, graph, config, session_id, usage_handler)

        await websocket.send_json({
            "type": "done",
            "session_id": session_id,
        })
    except Exception as e:
        logger.error("Error during graph execution: %r", e, exc_info=True)
        await websocket.send_json({"type": "error", "reason": "Graph execution failed"})
    finally:
        if uploaded_file_path and os.path.exists(uploaded_file_path):
            os.remove(uploaded_file_path)