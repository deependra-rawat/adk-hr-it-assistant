import os
import json
import asyncio
import base64
import warnings
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

from google.genai.types import Part, Content, Blob
from google.cloud import bigquery
from google.adk.runners import InMemoryRunner
from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from google_search_agent.agent import build_root_agent  # ✅ fixed import
from starlette.websockets import WebSocketDisconnect
from google.cloud import speech

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
load_dotenv()

APP_NAME = "ADK Streaming example"

# BigQuery setup
BQ_PROJECT = "generativeai-coe"
BQ_DATASET = "AgentDevelopmentKit"
BQ_TABLE = "convo_pairs_rajat"
bq_client = bigquery.Client()

try:
    speech_client = speech.SpeechClient()
    print("Speech-to-Text client initialized successfully.")
except Exception as e:
    print(f"Failed to initialize Speech-to-Text client: {e}")
    # Exit or handle the error as the app cannot function without it
    speech_client = None

ua_pair = {}

# ──────────────────────────────────────────────
# Speech-to-Text Utility Function
# ──────────────────────────────────────────────

def transcribe_base64_audio(base64_string: str) -> str:
    """Converts a Base64 audio string to text using Google Speech-to-Text."""
    if not speech_client or not base64_string:
        return ""
        
    try:
        # Decode the Base64 string to raw audio bytes
        audio_bytes = base64.b64decode(base64_string)

        # Prepare the audio object for the API
        recognition_audio = speech.RecognitionAudio(content=audio_bytes)
        
        # Configure the recognition request
        # NOTE: Assumes 16-bit PCM audio at 16000Hz.
        # This is a common format for web audio, but may need adjustment.
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code="en-US",  # Adjust to your target language
        )

        print("INFO: Transcribing audio...")
        response = speech_client.recognize(config=config, audio=recognition_audio)
        
        # Extract and return the most likely transcript
        if response and response.results:
            transcript = response.results[0].alternatives[0].transcript
            print(f"INFO: Transcription successful: '{transcript}'")
            return transcript
        else:
            print("WARNING: Transcription returned no results.")
            return ""
    except Exception as e:
        print(f"Speech-to-Text Error: {e}")
        return ""
    
    
# ──────────────────────────────────────────────
# BigQuery Utility Functions
# ──────────────────────────────────────────────


def save_message_to_bq(user_id_str, new_user_agent_pair_dict, current_session_id):

    user_type, session_id, old_row = get_latest_session_data_from_bq(user_id_str, current_session_id)
    if user_type == "NEW USER":
        print(1)
        user = new_user_agent_pair_dict["user"]
        agent = new_user_agent_pair_dict["agent"]
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        query = f"""
        INSERT INTO `{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}` (
            user_id, session_id, user_agent_pairs, timestamp
        )
        VALUES (
            '{user_id_str}', '{session_id}',
            [STRUCT('{user}' AS user, '{agent}' AS agent)],
            DATETIME '{timestamp}'
        )"""
        
        # print(user, agent)
        # print(query)
        # print(2)

        try:
            print(3)
            result = query_bq(query)
            print(result, type(result))
            print("✅ Insert Query executed successfully.")
        except Exception as e:
            print("❌ Query failed:", e)


    else:
        # OLD USER (in the same session)
        # Escape single quotes (for SQL safety)
        user = new_user_agent_pair_dict["user"].replace("'", "\\'")
        agent = new_user_agent_pair_dict["agent"].replace("'", "\\'")

        updated_query = f"""
                    UPDATE `{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`
                    SET user_agent_pairs = ARRAY_CONCAT(user_agent_pairs, [
                    STRUCT('{user}' AS user, '{agent}' AS agent)
                    ])
                    WHERE user_id = '{user_id_str}' AND session_id = '{session_id}'"""

        print(f"Generated SQL query:\n{updated_query}")

        try:
            result = query_bq(updated_query)
            print("row updated:", result)
        except Exception as e:
            print(e)


def query_bq(query):
    try:
        results = bq_client.query(query).result()
        return results
    except Exception as e:
        print(e)


def get_latest_session_data_from_bq(user_id, current_session_id):
    try:
        query = f"""
                SELECT * 
                FROM `{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}`
                WHERE user_id = '{user_id}' and session_id = '{current_session_id}'
                ORDER BY timestamp DESC
                LIMIT 1"""
        results = query_bq(query)
        row = list(results)
        if row:
            print("OLD USER")
            user_type = "OLD USER"
            return user_type, current_session_id, row[0]
        else:
            print("NEW USER")
            user_type = "NEW USER"
            return user_type, current_session_id, row # here the row is empty
    except Exception as e:
        print(e)

# ──────────────────────────────────────────────
# Agent Setup
# ──────────────────────────────────────────────

async def start_agent_session(user_id, is_audio=False):
    agent = build_root_agent(user_id)  # ✅ use agent builder
    runner = InMemoryRunner(app_name=APP_NAME, agent=agent)
    session = await runner.session_service.create_session(app_name=APP_NAME, user_id=user_id)
    modality = "AUDIO" if is_audio else "TEXT"
    run_config = RunConfig(response_modalities=[modality])
    live_request_queue = LiveRequestQueue()
    live_events = runner.run_live(session=session, live_request_queue=live_request_queue, run_config=run_config)

    return live_events, live_request_queue, session.id

# ──────────────────────────────────────────────
# WebSocket Messaging
# ──────────────────────────────────────────────

async def agent_to_client_messaging(websocket, live_events, user_id, current_session_id):
    global ua_pair
    full_text = ""
    full_audio_bytes = b""  # New: Accumulator for agent's raw audio bytes
    turn_saved = False

    async for event in live_events:
        part: Part = event.content and event.content.parts and event.content.parts[0]

        # Handle text parts (no changes here)
        if part and part.text:
            full_text += part.text
            turn_saved = False
            if event.partial:
                await websocket.send_text(json.dumps({
                    "mime_type": "text/plain",
                    "data": part.text
                }))

        # Handle audio parts
        elif part and part.inline_data and part.inline_data.mime_type.startswith("audio/pcm"):
            audio_data = part.inline_data.data
            if audio_data:
                # New: Accumulate raw audio bytes for saving
                full_audio_bytes += audio_data
                turn_saved = False
                
                # Stream audio chunk to client (no changes here)
                await websocket.send_text(json.dumps({
                    "mime_type": "audio/pcm",
                    "data": base64.b64encode(audio_data).decode("ascii")
                }))

        # Finalize and save the turn
        if event.turn_complete or event.interrupted:
            # Save text turn if it exists
            if full_text and not turn_saved:
                ua_pair["agent"] = full_text.split("\n")[0]
                save_message_to_bq(user_id, ua_pair, current_session_id)
                turn_saved = True

            # Save audio turn if it exists
            if full_audio_bytes and not turn_saved:
                # Encode all accumulated audio bytes to a single Base64 string
                agent_audio_b64 = base64.b64encode(full_audio_bytes).decode('ascii')
                agent_text = transcribe_base64_audio(agent_audio_b64)
                ua_pair["agent"] = agent_text
                save_message_to_bq(user_id, ua_pair, current_session_id)
                turn_saved = True

            # If a turn was saved, clear the state for the next one
            if turn_saved:
                full_text = ""
                full_audio_bytes = b""
                ua_pair.clear()

            # Send the final turn completion status to the client
            await websocket.send_text(json.dumps({
                "turn_complete": event.turn_complete,
                "interrupted": event.interrupted
            }))

async def client_to_agent_messaging(websocket, live_request_queue):
    try:
        while True:
            message_json = await websocket.receive_text()
            message = json.loads(message_json)
            mime_type = message["mime_type"]
            data = message["data"]
            ua_pair["user"] = data

            if mime_type == "text/plain":
                content = Content(role="user", parts=[Part.from_text(text=data)])
                live_request_queue.send_content(content=content)
            elif mime_type == "audio/pcm":
                decoded_data = base64.b64decode(data)
                live_request_queue.send_realtime(Blob(data=decoded_data, mime_type=mime_type))
            else:
                raise ValueError(f"Mime type not supported: {mime_type}")
    except WebSocketDisconnect:
        print("INFO: Client disconnected.")
    except Exception as e:
        print(f"Error in client to agent messaging: {e}")
    finally:
        live_request_queue.close()
# ──────────────────────────────────────────────
# FastAPI Setup
# ──────────────────────────────────────────────

app = FastAPI()
STATIC_DIR = Path("static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

# @app.get("/history/{user_id}")
# def get_history(user_id: str):
#     load_history_from_bq(user_id)
#     return conversation_history.get(user_id, [])

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int, is_audio: str):
    user_id = "Deeppppppeeennnndddrrraaa"
    await websocket.accept()
    user_id_str = str(user_id)

    # load_history_from_bq(user_id_str)
    # print(conversation_history)
    # print(user_sessions)
    live_events, live_request_queue, current_session_id = await start_agent_session(user_id_str, is_audio == "true")

    client_task = asyncio.create_task(client_to_agent_messaging(websocket, live_request_queue))
    agent_task = asyncio.create_task(agent_to_client_messaging(websocket, live_events, user_id_str, current_session_id))

    await asyncio.wait([agent_task, client_task], return_when=asyncio.FIRST_EXCEPTION)
    live_request_queue.close()
