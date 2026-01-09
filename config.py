import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-5")
OPENAI_TTS_MODEL_NAME = os.getenv("OPENAI_TTS_MODEL_NAME", "gpt-4o-mini-tts")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

DASHSCOPE_MODEL_NAME = os.getenv("DASHSCOPE_MODEL_NAME", "qwen3-max-preview")
DASHSCOPE_TTS_MODEL_NAME = os.getenv("DASHSCOPE_TTS_MODEL_NAME", "cosyvoice-v3-flash")
DASHSCOPE_VEO_MODEL_NAME = os.getenv("DASHSCOPE_VEO_MODEL_NAME", "wan2.6-t2v")
DASHSCOPE_API_KEY    = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL   = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash")
GEMINI_VEO_MODEL_NAME = os.getenv("GEMINI_VEO_MODEL_NAME", "veo-3.1-fast-generate-preview")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")

DEEPSEEK_MODEL_NAME = os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-reasoner")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL")

GLM_MODEL_NAME = os.getenv("GLM_MODEL_NAME", "glm-4.7")
GLM_API_KEY = os.getenv("GLM_API_KEY")
GLM_BASE_URL = os.getenv("GLM_BASE_URL")

ANTHROPIC_MODEL_NAME = os.getenv("ANTHROPIC_MODEL_NAME", "claude-sonnet-4-20250514")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")

LLAMA_MODEL_NAME = os.getenv("LLAMA_MODEL_NAME", "llama3:8b")
LLAMA_BASE_URL = os.getenv("LLAMA_BASE_URL", "http://localhost:11434/v1")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "myuanzhang/podcast")


