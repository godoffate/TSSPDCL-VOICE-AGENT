# main.py
import asyncio
import base64
import json
import websockets
import os
from dotenv import load_dotenv
from tssdcl_sql import FUNCTION_MAP  # async functions map

load_dotenv()

# in-memory conversation buffer per streamSid
conversation_buffers = {}  # streamSid -> {"user":[...], "assistant":[...]}


def sts_connect():
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        raise Exception("DEEPGRAM_API_KEY not found")

    sts_ws = websockets.connect(
        "wss://agent.deepgram.com/v1/agent/converse",
        subprotocols=["token", api_key]
    )
    return sts_ws


def load_config():
    with open("config.json", "r") as f:
        return json.load(f)


async def handle_barge_in(decoded, twilio_ws, streamsid):
    if decoded.get("type") == "UserStartedSpeaking":
        clear_message = {"event": "clear", "streamSid": streamsid}
        await twilio_ws.send(json.dumps(clear_message))


async def execute_function_call(func_name, arguments):
    if func_name not in FUNCTION_MAP:
        return {"error": f"Unknown function: {func_name}"}
    func = FUNCTION_MAP[func_name]
    try:
        result = await func(**arguments)
        print(f"Function call result: {result}")
        return result
    except Exception as e:
        print(f"Error executing function {func_name}: {e}")
        return {"error": f"Function execution failed: {str(e)}"}


def create_function_call_response(func_id, func_name, result):
    # For Deepgram Agent API, content should be a concise text summary or simple JSON
    # not a complex nested object
    if isinstance(result, dict):
        if result.get("error"):
            content_str = f"Error: {result['error']}"
        elif func_name == "lookup_complaint" and "complaint" in result:
            # Extract key info for a concise response
            comp = result["complaint"]
            status = comp.get("status", "unknown")
            complaint_no = comp.get("complaint_no", "N/A")
            complaint_id = comp.get("complaint_id", "N/A")
            created = comp.get("created_time", "N/A")
            
            # Create a simple, concise response
            content_str = f"Found complaint {complaint_no} with status: {status}. Created: {created[:10] if created != 'N/A' else 'N/A'}"
        elif func_name == "raise_complaint":
            complaint_no = result.get("complaint_no", "N/A")
            complaint_id = result.get("complaint_id", "N/A")[:8] + "..." if result.get("complaint_id") else "N/A"
            content_str = f"Complaint registered successfully. Number: {complaint_no}, ID: {complaint_id}"
        else:
            # Generic handling for other functions
            content_str = str(result.get("message", "Function completed successfully"))
    else:
        content_str = str(result)
    
    print("DEBUG: Creating FunctionCallResponse content:", content_str)
    return {"type": "FunctionCallResponse", "id": func_id, "name": func_name, "content": content_str}


async def handle_function_call_request(decoded, sts_ws, streamsid, audio_lock: asyncio.Lock):
    """
    Handle function call requests from STS.
    Acquire audio_lock while sending control messages to avoid interleaving with audio.
    """
    try:
        for function_call in decoded.get("functions", []):
            func_name = function_call["name"]
            func_id = function_call["id"]
            arguments = json.loads(function_call["arguments"])

            print(f"Function call: {func_name} (ID: {func_id}), arguments: {arguments}")

            # Execute the function (DB ops) outside lock
            result = await execute_function_call(func_name, arguments)

            # Acquire lock before any control send
            await audio_lock.acquire()
            try:
                function_result = create_function_call_response(func_id, func_name, result)
                fr_json = json.dumps(function_result)
                print("DEBUG: function_result JSON (len={}): {}".format(len(fr_json), fr_json))
                await sts_ws.send(fr_json)
                print("Sent function result")

                # small delay to help STS parsing
                await asyncio.sleep(0.05)
            finally:
                # always release lock
                audio_lock.release()

    except Exception as e:
        print(f"Error calling function: {e}")
        try:
            # safe fallback - acquire lock and notify STS of the error
            await audio_lock.acquire()
            try:
                await sts_ws.send(json.dumps(create_function_call_response(
                    function_call.get("id", "unknown"),
                    function_call.get("name", "unknown"),
                    {"error": f"Function call failed with: {str(e)}"}
                )))
                await asyncio.sleep(0.03)
            finally:
                audio_lock.release()
        except Exception:
            pass


async def handle_text_message(decoded, twilio_ws, sts_ws, streamsid, audio_lock: asyncio.Lock):
    await handle_barge_in(decoded, twilio_ws, streamsid)

    # Capture all user/assistant texts into conversation buffer
    if decoded.get("type") == "ConversationText":
        role = decoded.get("role")
        content = decoded.get("content", "").strip()
        if not content:
            return
        conversation_buffers.setdefault(streamsid, {"user": [], "assistant": []})
        if role == "user":
            conversation_buffers[streamsid]["user"].append(content)
        elif role == "assistant":
            conversation_buffers[streamsid]["assistant"].append(content)
        return

    if decoded.get("type") == "FunctionCallRequest":
        await handle_function_call_request(decoded, sts_ws, streamsid, audio_lock)


async def sts_sender(sts_ws, audio_queue, audio_lock: asyncio.Lock):
    """
    Send raw audio chunks to STS, but hold audio_lock to ensure mutual exclusion with control frames.
    """
    print("sts_sender started")
    try:
        while True:
            chunk = await audio_queue.get()
            # Acquire lock before sending audio; this ensures no control frame is being sent concurrently
            await audio_lock.acquire()
            try:
                await sts_ws.send(chunk)
            except websockets.exceptions.ConnectionClosedOK:
                print("sts_sender: STS connection closed (OK). Exiting sender loop.")
                break
            except Exception as e:
                print("sts_sender exception while sending media:", repr(e))
                break
            finally:
                audio_lock.release()
    except asyncio.CancelledError:
        print("sts_sender cancelled")
    finally:
        print("sts_sender exiting")


async def sts_receiver(sts_ws, twilio_ws, streamsid_queue, audio_lock: asyncio.Lock):
    print("sts_receiver started")
    streamsid = await streamsid_queue.get()

    async for message in sts_ws:
        if isinstance(message, str):
            print("STS Text:", message)
            decoded = json.loads(message)
            await handle_text_message(decoded, twilio_ws, sts_ws, streamsid, audio_lock)
            continue

        raw_mulaw = message
        media_message = {
            "event": "media",
            "streamSid": streamsid,
            "media": {"payload": base64.b64encode(raw_mulaw).decode("ascii")}
        }
        await twilio_ws.send(json.dumps(media_message))


async def twilio_receiver(twilio_ws, audio_queue, streamsid_queue):
    BUFFER_SIZE = 20 * 160
    inbuffer = bytearray(b"")
    streamsid = None

    async for message in twilio_ws:
        try:
            data = json.loads(message)
            event = data.get("event")

            if event == "start":
                start = data.get("start", {})
                streamsid = start.get("streamSid")
                conversation_buffers.setdefault(streamsid, {"user": [], "assistant": []})
                streamsid_queue.put_nowait(streamsid)
                print("get our streamsid", streamsid)
            elif event == "connected":
                continue
            elif event == "media":
                media = data["media"]
                chunk = base64.b64decode(media["payload"])
                if media.get("track") == "inbound":
                    inbuffer.extend(chunk)
            elif event == "stop":
                # cleanup buffer to free memory (DB retains records)
                if streamsid and streamsid in conversation_buffers:
                    del conversation_buffers[streamsid]
                break

            while len(inbuffer) >= BUFFER_SIZE:
                chunk = inbuffer[:BUFFER_SIZE]
                audio_queue.put_nowait(chunk)
                inbuffer = inbuffer[BUFFER_SIZE:]
        except Exception as e:
            print("twilio_receiver exception:", e)
            break


async def twilio_handler(twilio_ws):
    audio_queue = asyncio.Queue()
    streamsid_queue = asyncio.Queue()
    # Lock used to ensure control frames and audio frames don't interleave
    audio_lock = asyncio.Lock()

    async with sts_connect() as sts_ws:
        config_message = load_config()
        await sts_ws.send(json.dumps(config_message))

        await asyncio.wait(
            [
                asyncio.ensure_future(sts_sender(sts_ws, audio_queue, audio_lock)),
                asyncio.ensure_future(sts_receiver(sts_ws, twilio_ws, streamsid_queue, audio_lock)),
                asyncio.ensure_future(twilio_receiver(twilio_ws, audio_queue, streamsid_queue)),
            ],
            return_when=asyncio.FIRST_COMPLETED
        )

        await twilio_ws.close()


async def main():
    server = await websockets.serve(twilio_handler, "0.0.0.0", 5000)
    print("Started server on 0.0.0.0:5000")
    try:
        await asyncio.Future()
    finally:
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
