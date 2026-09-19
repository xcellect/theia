"""One real synthetic voice turn through Next, WebRTC, and the Gradium stack.

Uses configured paid providers. No microphone, speaker, audio files, transcripts,
or secret-bearing responses are printed. An existing session is never displaced.
Run with both local servers available: uv run --frozen python gradium_voice_smoke.py
"""

import asyncio
import base64
from contextlib import suppress
import json
import os
import re
import sys

from server import configure_safe_logging

configure_safe_logging()

import httpx
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from pipecat.transports.smallwebrtc.transport import RawAudioTrack
from websockets.asyncio.client import connect

from provider_probe import failure, gradium_message, gradium_ready
from voice_config import load_practice_environment, read_gradium_config


ORIGIN = "http://127.0.0.1:3000"
HEALTH = "/api/gradium/health"
OFFER = "/api/gradium/offer"
PHRASE = "Please say hello in one short sentence."


class SmokeFailure(Exception):
    """Only fixed diagnostic codes may be passed to this exception."""


async def health(client):
    response = await client.get(HEALTH)
    if response.status_code != 200:
        raise SmokeFailure("HEALTH_UNAVAILABLE")
    data = response.json()
    if data.get("configured") is not True or data.get("missing"):
        raise SmokeFailure("STACK_NOT_CONFIGURED")
    if data.get("activeSessions") != 0:
        raise SmokeFailure("SESSION_BUSY")


async def synthesize_input(config):
    chunks = []
    async with connect(config.tts_url,
                       additional_headers={"x-api-key": config.gradium_key},
                       open_timeout=10, close_timeout=2) as websocket:
        await websocket.send(json.dumps({"type": "setup", "model_name": "default",
            "output_format": "pcm", "voice_id": config.voice_id}))
        await gradium_ready(websocket, 48000)
        await websocket.send(json.dumps({"type": "text", "text": PHRASE}))
        await websocket.send(json.dumps({"type": "end_of_stream"}))
        while True:
            message = await gradium_message(websocket)
            if message.get("type") == "end_of_stream":
                break
            if message.get("type") == "audio":
                chunks.append(base64.b64decode(message["audio"], validate=True))
                if sum(map(len, chunks)) > 48000 * 2 * 12:
                    raise SmokeFailure("SYNTHETIC_INPUT_TOO_LONG")
    audio = b"".join(chunks)
    if not audio:
        raise SmokeFailure("NO_SYNTHETIC_INPUT")
    return audio


async def check():
    stats = {"ok": False, "stage": "health", "transcriptionCharacters": 0,
             "replyCharacters": 0, "nonSilentAudioFrames": 0,
             "sampleRate": 0, "cleanupVerified": False}
    peer = None
    input_track = None
    tasks = []
    offered = False
    config = None
    async with httpx.AsyncClient(base_url=ORIGIN, timeout=25, trust_env=False,
                                headers={"Origin": ORIGIN}) as client:
        try:
            async with asyncio.timeout(78):
                await health(client)
                load_practice_environment()
                config = read_gradium_config(os.environ)
                stats["stage"] = "synthetic-input"
                print("REAL REQUEST: synthesizing one short input phrase, then one integrated voice turn.", flush=True)
                async with asyncio.timeout(18):
                    audio = await synthesize_input(config)
                await health(client)  # Do not take over a session opened during synthesis.

                stats["stage"] = "webrtc-offer"
                peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
                input_track = RawAudioTrack(48000)
                peer.addTrack(input_track)
                channel = peer.createDataChannel("rtvi")
                channel_open = asyncio.Event()
                bot_ready = asyncio.Event()
                completed = asyncio.Event()
                provider_token = None
                final_transcription = False

                def check_complete():
                    if (final_transcription and stats["replyCharacters"] > 0
                            and stats["nonSilentAudioFrames"] >= 5):
                        completed.set()

                @channel.on("open")
                def opened():
                    channel_open.set()

                @channel.on("message")
                def message_received(raw):
                    nonlocal final_transcription, provider_token
                    if not isinstance(raw, str) or raw.startswith("pong"):
                        return
                    try:
                        message = json.loads(raw)
                    except (ValueError, TypeError):
                        return
                    data = message.get("data") or {}
                    kind = message.get("type")
                    if kind == "bot-ready":
                        bot_ready.set()
                    elif kind == "user-transcription" and data.get("final"):
                        text = data.get("text", "")
                        stats["transcriptionCharacters"] = len(text)
                        final_transcription = bool(text.strip())
                        stats["knownInputRecognized"] = "hello" in text.lower()
                    elif kind == "bot-output" and data.get("spoken_status") == "new":
                        stats["replyCharacters"] += len(data.get("text", ""))
                    elif kind == "error":
                        matched = re.match(r"^\[PIPECAT:(GENERALCOMPUTE|GRADIUM_STT|GRADIUM_TTS|PIPELINE):(AUTH|QUOTA|MODEL|VOICE|TIMEOUT|NETWORK|UNKNOWN)\]", str(data.get("error", "")))
                        provider_token = matched.group(0) if matched else "PIPELINE_ERROR"
                        completed.set()
                    check_complete()

                @peer.on("track")
                def track_received(track):
                    async def read_audio():
                        while True:
                            frame = await track.recv()
                            samples = frame.to_ndarray().astype("int32")
                            if frame.sample_rate == 48000 and abs(samples).max() > 150:
                                stats["sampleRate"] = frame.sample_rate
                                stats["nonSilentAudioFrames"] += 1
                                check_complete()
                    tasks.append(asyncio.create_task(read_audio()))

                await peer.setLocalDescription(await peer.createOffer())
                response = await client.post(OFFER, json={"sdp": peer.localDescription.sdp, "type": "offer"})
                if response.status_code != 200:
                    raise SmokeFailure("OFFER_REJECTED")
                answer = response.json()
                offered = True
                await peer.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
                await channel_open.wait()

                async def keep_alive():
                    while channel.readyState == "open":
                        channel.send("ping")
                        await asyncio.sleep(1)
                tasks.append(asyncio.create_task(keep_alive()))
                channel.send(json.dumps({"label": "rtvi-ai", "type": "client-ready", "id": "synthetic-smoke",
                    "data": {"version": "2.1.0", "about": {"library": "synthetic-smoke"}}}))
                stats["stage"] = "bot-ready"
                await bot_ready.wait()
                patch_response = await client.patch(OFFER, json={"pc_id": answer["pc_id"], "candidates": []})
                if patch_response.status_code != 200:
                    raise SmokeFailure("PATCH_REJECTED")

                stats["stage"] = "voice-turn"
                print("WebRTC and RTVI ready; sending synthetic speech and listening for the reply in memory.", flush=True)
                # A little leading silence lets native semantic VAD establish an idle baseline.
                await asyncio.sleep(0.8)
                chunk_bytes = 48000 * 2 // 100
                padded = audio + bytes((-len(audio)) % chunk_bytes)
                await input_track.add_audio_bytes(padded)
                # RawAudioTrack continues silence so native Gradium end-of-turn fires.
                await completed.wait()
                if provider_token:
                    stats["providerError"] = provider_token
                    raise SmokeFailure("PROVIDER_FAILURE")
                if not stats.get("knownInputRecognized"):
                    raise SmokeFailure("SYNTHETIC_TRANSCRIPT_MISMATCH")
                stats["ok"] = True
                stats["stage"] = "complete"
        except SmokeFailure as error:
            stats["reason"] = str(error)
        except Exception as error:
            # This helper classifies locally; it never returns provider response text.
            provider = "gradium-tts" if stats["stage"] == "synthetic-input" else "pipeline"
            stats["category"] = failure(provider, error)["category"]
        finally:
            if peer is not None:
                with suppress(Exception):
                    async with asyncio.timeout(4):
                        await peer.close()
            if input_track is not None:
                input_track.stop()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if offered:
                try:
                    async with asyncio.timeout(6):
                        while True:
                            response = await client.get(HEALTH)
                            if response.status_code == 200 and response.json().get("activeSessions") == 0:
                                stats["cleanupVerified"] = True
                                break
                            await asyncio.sleep(0.2)
                except Exception:
                    stats["ok"] = False
                    stats["cleanupVerified"] = False
    print(json.dumps(stats), flush=True)
    return 0 if stats["ok"] and stats["cleanupVerified"] else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(check()))
    except KeyboardInterrupt:
        print("Synthetic voice check cancelled.")
        sys.exit(130)
    except Exception:
        print("Synthetic voice check could not start. Check the local servers and installed dependencies.")
        sys.exit(1)
