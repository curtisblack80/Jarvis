"""Voice — the ears and mouth.

A thin layer around the existing brain. Input arrives as transcribed speech
instead of typed text; output is spoken aloud as well as printed. The brain in
the middle (Agent) is untouched: a spoken turn calls the same Agent.send a typed
turn does. If adding voice ever tempts you to fork the agent logic, stop.

Everything here sits behind a seam so the STT provider (Deepgram), the TTS
provider (ElevenLabs), and the capture method (push-to-talk) can each be swapped
in one place without touching the rest of the harness.
"""
