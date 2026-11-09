"""Shared helper so both POST /query and POST /analysis trigger the exact
same pipeline -- no duplicated orchestration logic between the two
endpoints the spec calls for.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.message import Message
from app.tasks.queue import get_task_queue


def _generate_session_title(query_text: str) -> str:
    cleaned = query_text.strip()
    starters = [
        "what is visible in this image", "what is visible in", "what is shown in this image",
        "describe this satellite image", "describe this image", "describe the image",
        "what is this image of", "what is this", "tell me about this", "tell me about",
        "where is the", "where is", "where are the", "where are", "can you locate",
        "can you find", "can you show me", "can you show", "please find", "please locate",
        "locate the", "locate", "find the", "find", "is there any", "are there any",
        "is there", "are there", "detect the", "detect",
    ]
    lower = cleaned.lower().rstrip("?.!,")
    for starter in starters:
        if lower.startswith(starter):
            remainder = cleaned[len(starter):].strip(" :,-?.!")
            if len(remainder) >= 3:
                cleaned = remainder
            break
    cleaned = cleaned[0].upper() + cleaned[1:] if cleaned else "Satellite Query"
    if len(cleaned) > 42:
        cleaned = cleaned[:40].rsplit(" ", 1)[0] + "..."
    return cleaned or "Satellite Query"


def submit_analysis(
    db: Session, session_id: str | None, query_text: str, image_ids: list[str]
) -> str:
    if session_id:
        from app.models.chat_session import ChatSession

        # Auto-name generic/new sessions from the user's first query
        session = db.get(ChatSession, session_id)
        if session and (
            not session.title
            or session.title in ("New Analysis", "New Satellite Query", "Satellite Analysis", "Untitled Analysis")
            or session.title.startswith("New Satellite Query")
        ):
            session.title = _generate_session_title(query_text)

        db.add(Message(session_id=session_id, role="user", content=query_text))
        db.commit()

    execution_id = get_task_queue().enqueue_analysis(db, session_id, query_text, image_ids)

    if session_id:
        from app.models.execution import Execution

        execution = db.get(Execution, execution_id)
        if execution and execution.result_json and execution.result_json.get("answer"):
            db.add(
                Message(
                    session_id=session_id,
                    role="assistant",
                    content=execution.result_json["answer"],
                    execution_id=execution_id,
                )
            )
        elif execution and execution.status in ("requires_user_input", "failed"):
            db.add(
                Message(
                    session_id=session_id,
                    role="assistant",
                    content=(execution.result_json or {}).get(
                        "user_message", "Additional input is required."
                    ),
                    execution_id=execution_id,
                )
            )
        db.commit()

    return execution_id
