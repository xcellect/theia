"""Prove installed service imports without making any provider requests."""
import inspect
import platform
from importlib.metadata import version
from pipecat.services.sambanova.llm import SambaNovaLLMService
from pipecat.services.hume.tts import HumeTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.gradium.stt import GradiumSTTService
from pipecat.services.gradium.tts import GradiumTTSService
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.audio.vad.silero import SileroVADAnalyzer
from voice_pipeline import BoundedGeneralComputeLLMService

print(f"Python {platform.python_version()}")
print(f"pipecat-ai {version('pipecat-ai')}")
for service in [SambaNovaLLMService, HumeTTSService, DeepgramSTTService, GradiumSTTService, GradiumTTSService, BoundedGeneralComputeLLMService, SmallWebRTCTransport, SileroVADAnalyzer]:
    print(f"PASS import: {service.__name__}{inspect.signature(service.__init__)}")
print("Import checks make no provider requests. Live microphone, transcription and audio still need a browser test.")
print("Start the local modular pipeline with: python server.py")
