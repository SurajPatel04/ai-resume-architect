from langchain.chat_models import init_chat_model
from dotenv import load_dotenv

load_dotenv()

def get_openai_llm():
    return init_chat_model("openai:gpt-4o-mini", temperature=0, stream_usage=True)

def get_openai_cheap_llm():
    return init_chat_model(
        "openai:gpt-5-nano",
        temperature=0,
        stream_usage=True,
        reasoning_effort="low"
    )

def get_google_llm_lite():
    return init_chat_model(
        "gemini-2.5-flash-lite",
        model_provider="google_vertexai",
        temperature=0,
        streaming=True
    )

def get_google_llm():
    return init_chat_model(
        "gemini-2.5-flash",
        model_provider="google_vertexai",
        temperature=0,
        streaming=True,
    )

