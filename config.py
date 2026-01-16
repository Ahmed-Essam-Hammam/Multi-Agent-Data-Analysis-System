import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Configuration Settings
class Settings:
    CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
    # This creates an absolute path to the 'uploads' folder in your project root
    UPLOAD_DIR = BASE_DIR / "CSV&SQL agent/uploads"
    MODEL_NAME = "llama-3.3-70b"

settings = Settings()

# Ensure upload directory exists
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

UPLOAD_DIR_STR = str(settings.UPLOAD_DIR)

# Initialize the LLM
llm = ChatOpenAI(
    base_url="https://api.cerebras.ai/v1",
    model=settings.MODEL_NAME,
    api_key=settings.CEREBRAS_API_KEY,
    temperature=0,
)