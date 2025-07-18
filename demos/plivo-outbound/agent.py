import logging

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    metrics,
    RoomInputOptions,
)
from livekit.plugins import (
    cartesia,
    openai,
    deepgram,
    noise_cancellation,
    silero,
    playai,
    google,
    groq,
    elevenlabs,
    sarvam,

)
import uuid

from livekit.agents.tts import TTSCapabilities

from livekit.agents import metrics, MetricsCollectedEvent
from livekit.plugins.elevenlabs import VoiceSettings
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from livekit.agents import function_tool, Agent, RunContext
import os

os.environ["HF_HUB_OFFLINE"] = "0"
from prompts import ads_prompt

load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("voice-agent")

from livekit import api
import json

class Assistant(Agent):
    def __init__(self) -> None:
        # This project is configured to use Deepgram STT, OpenAI LLM and Cartesia TTS plugins
        # Other great providers exist like Cerebras, ElevenLabs, Groq, Play.ht, Rime, and more
        # Learn more and pick the best one for your app:
        # https://docs.livekit.io/agents/plugins
        super().__init__(
            # instructions="You are a voice assistant created by LiveKit. Your interface with users will be voice. "
            # "You should use short and concise responses, and avoiding usage of unpronouncable punctuation. "
            # "You were created as a demo to showcase the capabilities of LiveKit's agents framework.",
            instructions = ads_prompt,

            # STT
            stt=deepgram.STT(   
                                model="nova-3",
                                language="multi",
            ),
            # stt=sarvam.STT(
            #     language="hi-IN",
            #     model="saarika:v2.5",
            # ),
            # llm=groq.LLM(
            #     model="meta-llama/llama-4-maverick-17b-128e-instruct",
            #     # model="meta-llama/llama-4-scout-17b-16e-instruct",
            #     temperature=0.5,
            # ),  
            llm=openai.LLM.with_azure(
                azure_deployment="gpt-4o-mini",
                azure_endpoint="https://nugget-sweden-central.openai.azure.com/", # or AZURE_OPENAI_ENDPOINT
                api_key="", # or AZURE_OPENAI_API_KEY
                api_version="2025-01-01-preview", # or OPENAI_API_VERSION
            ),
            # https://.openai.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=
            # tts=elevenlabs.TTS(
            #     voice_id="TRnaQb7q41oL7sV0w6Bu",
            #     # voice_id='tiOJmEGAP48WxpUIZO6g',
            #     model="eleven_flash_v2_5",
            #     # model='eleven_multilingual_v2',
            #     # model= 'eleven_v3',
            #     # streaming_latency = 0,
            #     # chunk_length_schedule = [100],
            #     voice_settings = VoiceSettings(
            #         stability = 0.8,
            #         similarity_boost = 0.75,
            #         speed = 0.9,
            #     ),
            # ),
            tts=cartesia.TTS(
                model="sonic-2-2025-05-08",
                voice="10142c39-93ac-49d7-8bb6-8e727a4e82b9",
                language="hi"
            ),
            # use LiveKit's transformer-based turn detector
            turn_detection=MultilingualModel(),
        )

    async def on_enter(self):
        # The agent should be polite and greet the user when it joins :)
        self.session.generate_reply(
            instructions="Hey, how can I help you today?", allow_interruptions=True
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    logger.info(f"connecting to room {ctx.room.name}")

    # file_contents = ""
    # with open("demos/plivo-outbound-calling/credentials.json", "r") as f:
    #   file_contents = f.read()

    # session_id = str(uuid.uuid4())
    # # Set up recording
    # req = api.RoomCompositeEgressRequest(
    #     room_name=ctx.room.name,
    #     layout="speaker",
    #     preset=api.EncodingOptionsPreset.H264_720P_30,
    #     audio_only=True,
    #     segment_outputs=[api.SegmentedFileOutput(
    #         filename_prefix=session_id + "/" + "my-output",
    #         playlist_name=session_id + "/" +"my-playlist.m3u8",
    #         live_playlist_name=session_id + "/" + "my-live-playlist.m3u8",
    #         segment_duration=60,
    #         gcp=api.GCPUpload(
    #             credentials=file_contents,
    #             bucket="livekit-recording-demo",
    #         ),
    #     )],
    # )
    # lkapi = api.LiveKitAPI()
    # res = await lkapi.egress.start_room_composite_egress(req)
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    # await lkapi.aclose()
    # await ctx.connect()

    # If a phone number was provided, then place an outbound call
    # By having a condition like this, you can use the same agent for inbound/outbound telephony as well as web/mobile/etc.
    dial_info = json.loads(ctx.job.metadata)
    phone_number = dial_info["phone_number"]

    # The participant's identity can be anything you want, but this example uses the phone number itself
    sip_participant_identity = phone_number
    if phone_number is not None:
        # The outbound call will be placed after this method is executed
        try:
            await ctx.api.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                # This ensures the participant joins the correct room
                room_name=ctx.room.name,

                # This is the outbound trunk ID to use (i.e. which phone number the call will come from)
                # You can get this from LiveKit CLI with `lk sip outbound list`
                sip_trunk_id='ST_hgMSXkbSPmc2',

                # The outbound phone number to dial and identity to use
                sip_call_to=phone_number,
                participant_identity=sip_participant_identity,

                # This will wait until the call is answered before returning
                wait_until_answered=True,
            ))

            print("call picked up successfully")
        except api.TwirpError as e:
            print(f"error creating SIP participant: {e.message}, "
                  f"SIP status: {e.metadata.get('sip_status_code')} "
                  f"{e.metadata.get('sip_status')}")
            ctx.shutdown()

    # Wait for the first participant to connect
    participant = await ctx.wait_for_participant()
    logger.info(f"starting voice assistant for participant {participant.identity}")

    usage_collector = metrics.UsageCollector()

    # Log metrics and collect usage data
    def on_metrics_collected(agent_metrics: metrics.AgentMetrics):
        metrics.log_metrics(agent_metrics)
        usage_collector.collect(agent_metrics)
        logger.info(f"Metrics collected: {agent_metrics}")
    
    # async def log_usage():
    #     summary = usage_collector.get_summary()
    #     logger.info(f"Usage: {summary}")


    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        # minimum delay for endpointing, used when turn detector believes the user is done with their turn
        min_endpointing_delay=0.5,
        # maximum delay for endpointing, used when turn detector does not believe the user is done with their turn
        max_endpointing_delay=5.0,
    )

    # Trigger the on_metrics_collected function when metrics are collected
    session.on("metrics_collected", on_metrics_collected)

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_input_options=RoomInputOptions(
            # enable background voice & noise cancellation, powered by Krisp
            # included at no additional cost with LiveKit Cloud
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )
    if phone_number is None:
        await session.generate_reply(
            instructions="Greet the user and offer your assistance."
        )

    # def _on_metrics_collected(ev: MetricsCollectedEvent):
    #     metrics.log_metrics(ev.metrics)
    
    # async def log_usage():
    #     summary = usage_collector.get_summary()
    #     logger.info(f"Usage: {summary}")

    # session.on("metrics_collected", _on_metrics_collected)
    # session.on("usage_collected", log_usage)
    
    
    


# if __name__ == "__main__":
#     cli.run_app(
#         WorkerOptions(
#             entrypoint_fnc=entrypoint,
#             prewarm_fnc=prewarm,
#         ),
#     )
if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm,
        # agent_name is required for explicit dispatch
        agent_name="laura-voice-agent"
    ))
