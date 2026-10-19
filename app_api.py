import os

import streamlit as st
from streamlit_mic_recorder import mic_recorder

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional; you can paste keys in the sidebar instead

st.set_page_config(
    page_title="AI Meeting Summarizer",
    page_icon="🎙️",
    layout="wide",
)

SYSTEM_PROMPT = """
You are an expert meeting assistant. Use only information
supported by the transcript. Never invent owners, decisions,
or deadlines. Mark missing details as "Not specified".

Create these sections:

1. Executive Summary
2. Key Discussion Points
3. Decisions Made
4. Action Items, including task, owner, and deadline
   when mentioned
5. Unresolved Questions

Keep the notes concise, clear, and professional.
"""

# Default model names. Providers retire models often, so you can edit
# these in the sidebar without touching the code.
DEFAULTS = {
    "Groq": {
        "stt": "whisper-large-v3-turbo",
        "llm": "openai/gpt-oss-120b",
        "env": "GROQ_API_KEY",
    },
    "Gemini": {
        "stt": "gemini-3.5-flash",
        "llm": "gemini-3.5-flash",
        "env": "GEMINI_API_KEY",
    },
}

# ---------------- Sidebar: provider, key, models ----------------
with st.sidebar:
    st.header("⚙️ Settings")
    provider = st.selectbox("Provider", list(DEFAULTS.keys()))
    cfg = DEFAULTS[provider]

    # The key is never pre-filled into the page. If the box is empty, the app
    # silently uses the server-side key (.env locally, Secrets when deployed).
    typed_key = st.text_input(
        f"{provider} API key (optional)",
        value="",
        type="password",
        help=f"Leave blank to use the server's {cfg['env']}, or paste your own.",
    ).strip()
    api_key = typed_key or os.getenv(cfg["env"], "")

    if provider == "Groq":
        stt_model = st.text_input("Transcription model", cfg["stt"])
        llm_model = st.text_input("Notes model", cfg["llm"])
    else:
        stt_model = st.text_input("Transcription model (Gemini)", cfg["stt"])
        llm_model = st.text_input("Notes model (Gemini)", cfg["llm"])

    if st.button("🔍 Test key / list models", use_container_width=True):
        if not api_key:
            st.error("Enter an API key first.")
        else:
            try:
                if provider == "Groq":
                    from groq import Groq
                    models = Groq(api_key=api_key).models.list()
                    names = sorted(m.id for m in models.data)
                else:
                    from google import genai
                    client = genai.Client(api_key=api_key)
                    names = sorted(
                        m.name.replace("models/", "")
                        for m in client.models.list()
                    )
                st.success("Key works! Available models:")
                st.code("\n".join(names))
            except Exception as e:
                st.error(f"Key test failed: {e}")

st.title("🎙️ AI Meeting Summarizer")
st.subheader(
    "Record a meeting, generate a transcript, and extract "
    "decisions and actionable meeting notes."
)

# ---------------- Session state ----------------
defaults = {
    "transcription": "",
    "meeting_notes": "",
    "audio_bytes": None,
    "audio_format": "wav",
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

if not api_key:
    st.warning(f"Paste your {provider} API key in the sidebar to begin.")
    st.stop()


# ---------------- Provider functions ----------------
def transcribe(audio_bytes: bytes, fmt: str) -> str:
    if provider == "Groq":
        from groq import Groq

        client = Groq(api_key=api_key)
        result = client.audio.transcriptions.create(
            file=(f"meeting.{fmt}", audio_bytes),
            model=stt_model,
        )
        return (result.text or "").strip()

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=stt_model,
        contents=[
            "Transcribe this audio exactly as spoken. "
            "Return only the transcript text, nothing else.",
            types.Part.from_bytes(data=audio_bytes, mime_type=f"audio/{fmt}"),
        ],
    )
    return (response.text or "").strip()


def make_notes(transcript: str) -> str:
    if provider == "Groq":
        from groq import Groq

        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
        )
        return response.choices[0].message.content or ""

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=llm_model,
        contents=transcript,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
    )
    return response.text or ""


# ---------------- Layout ----------------
layout_col1, layout_col2 = st.columns([1, 2])

with layout_col1:
    st.header("1. Capture Audio")
    st.write("Start recording, speak clearly, then stop recording.")

    audio_data = mic_recorder(
        start_prompt="🎙️ Start recording",
        stop_prompt="⏹️ Stop recording",
        key="recorder",
    )

    if audio_data and audio_data.get("bytes"):
        st.session_state.audio_bytes = audio_data["bytes"]

        audio_bytes = st.session_state.audio_bytes
        if audio_bytes.startswith(b"RIFF") and audio_bytes[8:12] == b"WAVE":
            st.session_state.audio_format = "wav"
        else:
            st.session_state.audio_format = "webm"

        st.session_state.transcription = ""
        st.session_state.meeting_notes = ""

    if st.session_state.audio_bytes:
        st.success("Audio ready!")
        st.audio(
            st.session_state.audio_bytes,
            format=f"audio/{st.session_state.audio_format}",
        )
        if provider == "Gemini" and st.session_state.audio_format == "webm":
            st.warning(
                "Gemini doesn't accept WebM audio. Use Groq for this recording."
            )

    generate = st.button(
        "✨ Generate Transcript & Meeting Notes",
        type="primary",
        disabled=not bool(st.session_state.audio_bytes),
        use_container_width=True,
    )

    if generate:
        try:
            with st.spinner("Transcribing meeting audio..."):
                st.session_state.transcription = transcribe(
                    st.session_state.audio_bytes,
                    st.session_state.audio_format,
                )

            if not st.session_state.transcription:
                st.warning("No speech was detected. Try a clearer recording.")
            else:
                with st.spinner("Generating structured meeting notes..."):
                    st.session_state.meeting_notes = make_notes(
                        st.session_state.transcription
                    )
                st.success("Meeting summary generated successfully!")

        except Exception as e:
            # Shows the real error so you can see what's wrong
            st.error(f"{provider} error: {e}")

with layout_col2:
    st.header("2. Transcript & AI Insights")

    tab1, tab2 = st.tabs(
        ["📝 Raw Transcript", "📋 Structured Meeting Notes"]
    )

    with tab1:
        if st.session_state.transcription:
            st.text_area(
                "Meeting Transcript",
                value=st.session_state.transcription,
                height=400,
            )
        else:
            st.info("Your transcript will appear here.")

    with tab2:
        if st.session_state.meeting_notes:
            st.markdown(st.session_state.meeting_notes)
        else:
            st.info("Your structured meeting notes will appear here.")

st.divider()
st.header("3. Download & Save")

down_col1, down_col2, down_col3 = st.columns(3)

with down_col1:
    st.download_button(
        "⬇️ Download Audio",
        data=st.session_state.audio_bytes or b"",
        file_name=f"meeting_audio.{st.session_state.audio_format}",
        mime=f"audio/{st.session_state.audio_format}",
        disabled=not bool(st.session_state.audio_bytes),
        use_container_width=True,
    )

with down_col2:
    st.download_button(
        "⬇️ Download Transcript",
        data=st.session_state.transcription,
        file_name="meeting_transcript.txt",
        mime="text/plain",
        disabled=not bool(st.session_state.transcription),
        use_container_width=True,
    )

with down_col3:
    st.download_button(
        "⬇️ Download Meeting Notes",
        data=st.session_state.meeting_notes,
        file_name="meeting_notes.txt",
        mime="text/plain",
        disabled=not bool(st.session_state.meeting_notes),
        use_container_width=True,
    )
