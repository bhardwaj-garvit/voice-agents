#!/bin/bash
set -e

# Install main agents package
pip install -e ./livekit-agents

# Install all plugins except browser and blingfire
pip install -e ./livekit-plugins/livekit-plugins-openai
pip install -e ./livekit-plugins/livekit-plugins-cartesia
pip install -e ./livekit-plugins/livekit-plugins-deepgram
pip install -e ./livekit-plugins/livekit-plugins-playai
pip install -e ./livekit-plugins/livekit-plugins-silero
pip install -e ./livekit-plugins/livekit-plugins-turn-detector

pip install -e ./livekit-plugins/livekit-plugins-sarvam
pip install -e ./livekit-plugins/livekit-plugins-groq