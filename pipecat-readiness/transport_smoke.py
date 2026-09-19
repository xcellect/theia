"""Real local WebRTC/audio/data-channel check using synthetic audio, no providers.

This needs permission to open local UDP sockets. It never loads .env files,
uses no API keys, and does not prove browser microphone or provider behavior.
"""
import asyncio
import json
import logging

from loguru import logger

logger.remove()
logging.disable(logging.CRITICAL)

from aiortc import AudioStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from pipecat.transports.smallwebrtc.request_handler import ConnectionMode, SmallWebRTCRequestHandler
from server import OfferBody, PatchBody, SessionManager


class SyntheticSession:
    def __init__(self, connection, _config):
        self.connection = connection
        self.ended = asyncio.Event()
        self.closed = False
        self.audio = AudioStreamTrack()
        connection.replace_audio_track(self.audio)

        @connection.event_handler("app-message")
        async def on_message(peer, message):
            peer.send_app_message({"type": "fixture-echo", "text": message["text"]})

    async def run(self):
        await self.connection.connect()
        await self.ended.wait()

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.audio.stop()
        self.ended.set()
        await self.connection.disconnect()


async def check():
    peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    input_track = AudioStreamTrack()
    peer.addTrack(input_track)
    channel = peer.createDataChannel("rtvi")
    opened = asyncio.Event()
    received = asyncio.get_running_loop().create_future()
    audio_received = asyncio.get_running_loop().create_future()
    audio_tasks = []

    @channel.on("open")
    def on_open():
        opened.set()

    @channel.on("message")
    def on_message(message):
        data = json.loads(message)
        if data.get("type") == "fixture-echo" and not received.done():
            received.set_result(data)

    @peer.on("track")
    def on_track(track):
        async def read_audio():
            frame = await track.recv()
            if not audio_received.done():
                audio_received.set_result(frame)
        audio_tasks.append(asyncio.create_task(read_audio()))

    handler = SmallWebRTCRequestHandler(ice_servers=[], connection_mode=ConnectionMode.SINGLE)
    manager = SessionManager(handler, SyntheticSession)
    try:
        async with asyncio.timeout(25):
            await peer.setLocalDescription(await peer.createOffer())
            answer = await manager.offer(OfferBody(sdp=peer.localDescription.sdp, type="offer"), None)
            assert answer["type"] == "answer" and answer["pc_id"]
            await peer.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
            await opened.wait()
            channel.send(json.dumps({"type": "fixture", "text": "synthetic transport check"}))
            assert (await received)["text"] == "synthetic transport check"
            frame = await audio_received
            assert frame.sample_rate == 48000 and frame.samples > 0
            await manager.patch(PatchBody(pc_id=answer["pc_id"], candidates=[]))
            assert manager.active_sessions == 1
    finally:
        await manager.close()
        await peer.close()
        input_track.stop()
        for task in audio_tasks:
            task.cancel()
        await asyncio.gather(*audio_tasks, return_exceptions=True)
    assert manager.active_sessions == 0
    print("PASS: actual local WebRTC negotiation, data-channel round trip, 48 kHz synthetic audio, PATCH, and cleanup.")
    print("No provider calls, API keys, microphone capture, or audible playback. Browser/headset testing remains separate.")


if __name__ == "__main__":
    asyncio.run(check())
