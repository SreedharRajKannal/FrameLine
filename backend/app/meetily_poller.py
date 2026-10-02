"""
meetily_poller.py – Polls the Meetily API for new completed meetings.

Since Meetily Pro blocks webhook registrations to private/loopback URLs,
this module provides an alternative: a background polling loop that checks
for new meetings every POLL_INTERVAL seconds and automatically imports
any transcripts that Frameline hasn't seen yet.

Owned by Sreedhar.
"""
import asyncio
import logging
import os
import time

from backend.app import config, store

logger = logging.getLogger(__name__)

# How often to poll Meetily for new meetings (seconds)
POLL_INTERVAL = int(os.getenv("MEETILY_POLL_INTERVAL", "10"))

# Track known meeting IDs to avoid re-processing
_known_meeting_ids: set[str] = set()
_poller_task: asyncio.Task | None = None


def _get_known_meetings() -> set[str]:
    """Load already-imported meeting IDs from our database."""
    meetings = store.list_meetings()
    # Extract the meetily source IDs we've already imported
    ids = set()
    for m in meetings:
        mid = m.get("meeting_id", "")
        ids.add(mid)
        # Also track the original meetily ID if we prefixed it
        if mid.startswith("meetily-"):
            ids.add(mid)
    return ids


async def _poll_loop():
    """
    Main polling loop. Runs forever in the background.
    
    On each tick:
    1. Calls meetily_client.list_meetings() to get all Meetily meetings.
    2. Filters to only meetings we haven't imported yet.
    3. For each new meeting, fetches the transcript and runs the pipeline.
    """
    global _known_meeting_ids
    
    # Import here to avoid circular imports
    from backend.app import meetily_client
    from backend.app.pipeline import process_transcript
    from backend.app.llm import call_llm
    
    # Seed with existing meetings from our DB
    _known_meeting_ids = _get_known_meetings()
    logger.info("Meetily poller started (interval=%ds, %d existing meetings tracked)",
                POLL_INTERVAL, len(_known_meeting_ids))
    
    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL)
            
            if not meetily_client.is_reachable():
                continue
            
            # Get all meetings from Meetily
            try:
                meetily_meetings = meetily_client.list_meetings()
            except Exception as e:
                logger.debug("Failed to list Meetily meetings: %s", e)
                continue
            
            for meeting in meetily_meetings:
                meetily_id = meeting.get("id", "")
                if not meetily_id:
                    continue
                
                # Check if this meeting's transcript is ready (if status field is provided by API)
                status = meeting.get("status", "")
                if status and status in ("recording", "processing", "failed"):
                    continue
                
                # Build the ID we'd use in our DB
                our_id = f"meetily-{meetily_id}"
                
                # Skip if we already know about it
                if our_id in _known_meeting_ids or meetily_id in _known_meeting_ids:
                    continue
                
                logger.info("New Meetily meeting detected: %s (status=%s)", meetily_id, status)
                
                # Fetch transcript from Meetily
                try:
                    transcript = meetily_client.get_transcript(meetily_id)
                    # Override meeting_id so we can track it
                    transcript.meeting_id = our_id
                except Exception as e:
                    logger.error("Failed to fetch transcript for %s: %s", meetily_id, e)
                    _known_meeting_ids.add(our_id)  # Don't retry endlessly
                    continue
                
                # Store transcript
                store.save_transcript(transcript, status="processing")
                _known_meeting_ids.add(our_id)
                logger.info("Imported transcript for %s (%d segments)", our_id, len(transcript.segments))
                
                # Run pipeline in a thread so we don't block the poller
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, _process_meeting, transcript
                    )
                except Exception as e:
                    logger.exception("Pipeline failed for %s: %s", our_id, e)
                    store.update_meeting_status(our_id, "failed")
                    
        except asyncio.CancelledError:
            logger.info("Meetily poller cancelled")
            break
        except Exception as e:
            logger.exception("Meetily poller error: %s", e)
            await asyncio.sleep(5)  # Brief pause before retry


def _process_meeting(transcript):
    """Run the full pipeline on a newly imported transcript (runs in executor thread)."""
    from backend.app.pipeline import process_transcript
    from backend.app.llm import call_llm
    
    meeting_id = transcript.meeting_id
    _log = logging.getLogger(__name__)
    
    try:
        # Generate title if missing
        if not transcript.title or transcript.title == "Untitled":
            text = " ".join([s.text for s in transcript.segments[:20]])
            if text.strip() and os.getenv("MOCK_LLM", "0") == "0":
                sys_prompt = (
                    "You are an AI that generates a very short, concise title for a meeting transcript. "
                    "Rules:\n"
                    "1. MUST be under 50 characters.\n"
                    "2. ONLY output the title, no quotes, no extra text, no explanations.\n"
                    "3. Do not invent details not present in the text (No hallucinations).\n"
                    "4. If you cannot determine a title, output exactly 'Untitled Meeting'."
                )
                prompt = f"Generate a title based on this conversation snippet:\n{text}"
                try:
                    title = call_llm(prompt, system=sys_prompt, json_mode=False)
                    title = title.strip(' "\'')
                    if title and len(title) <= 60:
                        store.update_meeting_title(meeting_id, title)
                except Exception as e:
                    _log.error("Failed to generate title: %s", e)

        settings = store.get_settings(meeting_id)
        items = process_transcript(transcript, settings)
        _log.info("Pipeline produced %d items for %s", len(items), meeting_id)
        if items:
            store.save_items(meeting_id, items)
            _log.info("Saved %d items for %s", len(items), meeting_id)
        else:
            _log.warning("Pipeline returned 0 items for %s", meeting_id)

        store.update_meeting_status(meeting_id, "completed")
    except Exception as exc:
        _log.exception("Pipeline failed for %s: %s", meeting_id, exc)
        store.update_meeting_status(meeting_id, "failed")


def start_poller():
    """Start the poller as an asyncio background task."""
    global _poller_task
    if _poller_task is not None and not _poller_task.done():
        logger.info("Poller already running")
        return
    _poller_task = asyncio.create_task(_poll_loop())
    logger.info("Meetily poller task created")


def stop_poller():
    """Cancel the poller task."""
    global _poller_task
    if _poller_task is not None and not _poller_task.done():
        _poller_task.cancel()
        _poller_task = None
        logger.info("Meetily poller task cancelled")
