import logging
from dataclasses import dataclass, field
from typing import Optional

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

from livekit.agents.tts import TTSCapabilities

from livekit.agents import metrics, MetricsCollectedEvent
from livekit.plugins.elevenlabs import VoiceSettings
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from livekit.agents import function_tool, Agent, RunContext


from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.llm import function_tool
from livekit.agents.voice import Agent, AgentSession, RunContext
from livekit.plugins import cartesia, deepgram, openai, silero
from livekit.plugins import noise_cancellation
from prompts import triage_prompt, billing_prompt, support_prompt
import json
# from utils import load_prompt

logger = logging.getLogger("medical-office-triage")
logger.setLevel(logging.INFO)
from livekit import api
load_dotenv(dotenv_path=".env.local")

@dataclass
class UserData:
    """Stores data and agents to be shared across the session"""
    personas: dict[str, Agent] = field(default_factory=dict)
    prev_agent: Optional[Agent] = None
    ctx: Optional[JobContext] = None

    def summarize(self) -> str:
        return "Call has been transferred to you by the previous agent, assist the user with their request"

RunContext_T = RunContext[UserData]

class BaseAgent(Agent):
    async def on_enter(self) -> None:
        agent_name = self.__class__.__name__
        logger.info(f"Entering {agent_name}")

        userdata: UserData = self.session.userdata
        if userdata.ctx and userdata.ctx.room:
            await userdata.ctx.room.local_participant.set_attributes({"agent": agent_name})

        chat_ctx = self.chat_ctx.copy()

        if userdata.prev_agent:
            items_copy = self._truncate_chat_ctx(
                userdata.prev_agent.chat_ctx.items, keep_function_call=True
            )
            existing_ids = {item.id for item in chat_ctx.items}
            items_copy = [item for item in items_copy if item.id not in existing_ids]
            chat_ctx.items.extend(items_copy)
            logger.info("call transferred with ctx", chat_ctx)

        chat_ctx.add_message(
            role="system",
            content=f"You are the {agent_name}. {userdata.summarize()}"
        )
        await self.update_chat_ctx(chat_ctx)
        self.session.generate_reply()

    def _truncate_chat_ctx(
        self,
        items: list,
        keep_last_n_messages: int = 20,
        keep_system_message: bool = False,
        keep_function_call: bool = False,
    ) -> list:
        """Truncate the chat context to keep the last n messages."""
        def _valid_item(item) -> bool:
            if not keep_system_message and item.type == "message" and item.role == "system":
                return False
            if not keep_function_call and item.type in ["function_call", "function_call_output"]:
                return False
            return True

        new_items = []
        for item in reversed(items):
            if _valid_item(item):
                new_items.append(item)
            if len(new_items) >= keep_last_n_messages:
                break
        new_items = new_items[::-1]

        while new_items and new_items[0].type in ["function_call", "function_call_output"]:
            new_items.pop(0)

        return new_items

    async def _transfer_to_agent(self, name: str, context: RunContext_T) -> Agent:
        """Transfer to another agent while preserving context"""
        userdata = context.userdata
        current_agent = context.session.current_agent
        next_agent = userdata.personas[name]
        userdata.prev_agent = current_agent

        return next_agent


class TriageAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            instructions=triage_prompt,
            stt=deepgram.STT(   
                                model="nova-3",
                                language="multi",
            ),
            llm=groq.LLM(
                model="meta-llama/llama-4-maverick-17b-128e-instruct",
                # model="meta-llama/llama-4-scout-17b-16e-instruct",
                temperature=0.5,
            ), 
            # tts=cartesia.TTS(),
            tts=elevenlabs.TTS(
                voice_id="RXe6OFmxoC0nlSWpuCDy",
                # voice_id='tiOJmEGAP48WxpUIZO6g',
                model="eleven_flash_v2_5",
                # model='eleven_multilingual_v2',
                # model= 'eleven_v3',
                streaming_latency = 0,
                # chunk_length_schedule = [100],
                voice_settings = VoiceSettings(
                    stability = 0.8,
                    similarity_boost = 0.75,
                    speed = 0.9,
                ),
            ),
            vad=silero.VAD.load()
        )

    @function_tool
    async def transfer_to_support(self, context: RunContext_T) -> Agent:
        await self.session.say("I'll transfer you to our Patient Support team who can help with your medical services request.")
        return await self._transfer_to_agent("support", context)

    @function_tool
    async def transfer_to_billing(self, context: RunContext_T) -> Agent:
        await self.session.say("I'll transfer you to our Medical Billing department who can assist with your insurance and payment questions.")
        return await self._transfer_to_agent("billing", context)


class SupportAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            instructions=support_prompt,
            stt=deepgram.STT(   
                                model="nova-3",
                                language="multi",
            ),
            llm=groq.LLM(
                model="meta-llama/llama-4-maverick-17b-128e-instruct",
                # model="meta-llama/llama-4-scout-17b-16e-instruct",
                temperature=0.5,
            ), 
            # tts=cartesia.TTS(),
            tts=elevenlabs.TTS(
                voice_id="kiaJRdXJzloFWi6AtFBf",
                # voice_id='tiOJmEGAP48WxpUIZO6g',
                model="eleven_flash_v2_5",
                # model='eleven_multilingual_v2',
                # model= 'eleven_v3',
                streaming_latency = 0,
                # chunk_length_schedule = [100],
                voice_settings = VoiceSettings(
                    stability = 0.8,
                    similarity_boost = 0.75,
                    speed = 0.9,
                ),
            ),
            vad=silero.VAD.load()
        )

    @function_tool
    async def transfer_to_triage(self, context: RunContext_T) -> Agent:
        await self.session.say("I'll transfer you back to our Medical Office Triage agent who can better direct your inquiry.")
        return await self._transfer_to_agent("triage", context)

    @function_tool
    async def transfer_to_billing(self, context: RunContext_T) -> Agent:
        await self.session.say("I'll transfer you to our Medical Billing department for assistance with your insurance and payment questions.")
        return await self._transfer_to_agent("billing", context)


class BillingAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            instructions=billing_prompt,
            stt=deepgram.STT(   
                                model="nova-3",
                                language="multi",
            ),
            llm=groq.LLM(
                model="meta-llama/llama-4-maverick-17b-128e-instruct",
                # model="meta-llama/llama-4-scout-17b-16e-instruct",
                temperature=0.5,
            ), 
            # tts=cartesia.TTS(),
            tts=elevenlabs.TTS(
                voice_id="4jclS1fxRk9w1EwYENqX",
                # voice_id='tiOJmEGAP48WxpUIZO6g',
                model="eleven_flash_v2_5",
                # model='eleven_multilingual_v2',
                # model= 'eleven_v3',
                streaming_latency = 0,
                # chunk_length_schedule = [100],
                voice_settings = VoiceSettings(
                    stability = 0.8,
                    similarity_boost = 0.75,
                    speed = 0.9,
                ),
            ),
            vad=silero.VAD.load()
        )

    @function_tool
    async def transfer_to_triage(self, context: RunContext_T) -> Agent:
        await self.session.say("I'll transfer you back to our Medical Office Triage agent who can better direct your inquiry.")
        return await self._transfer_to_agent("triage", context)

    @function_tool
    async def transfer_to_support(self, context: RunContext_T) -> Agent:
        await self.session.say("I'll transfer you to our Patient Support team who can help with your medical services request.")
        return await self._transfer_to_agent("support", context)


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    dial_info = json.loads(ctx.job.metadata)
    phone_number = dial_info["phone_number"]

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

    userdata = UserData(ctx=ctx)
    triage_agent = TriageAgent()
    support_agent = SupportAgent()
    billing_agent = BillingAgent()

    # Register all agents in the userdata
    userdata.personas.update({
        "triage": triage_agent,
        "support": support_agent,
        "billing": billing_agent
    })

    session = AgentSession[UserData](userdata=userdata,         
                                     vad=ctx.proc.userdata["vad"],
                                    # minimum delay for endpointing, used when turn detector believes the user is done with their turn
                                    min_endpointing_delay=0.5,
                                    # maximum delay for endpointing, used when turn detector does not believe the user is done with their turn
                                    max_endpointing_delay=5.0,
                            )

    # await session.start(
    #     agent=triage_agent,  # Start with the Medical Office Triage agent
    #     room=ctx.room,
    # )

    # Trigger the on_metrics_collected function when metrics are collected
    session.on("metrics_collected", on_metrics_collected)

    await session.start(
        room=ctx.room,
        agent=triage_agent,
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
def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

    

if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm,
        # agent_name is required for explicit dispatch
        agent_name="laura-voice-agent"
    ))