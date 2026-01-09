import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

DASHSCOPE_MODEL_NAME = os.getenv("DASHSCOPE_MODEL_NAME", "qwen3-max-preview")
DASHSCOPE_TTS_MODEL_NAME = os.getenv("DASHSCOPE_TTS_MODEL_NAME", "cosyvoice-v3-flash")
DASHSCOPE_VEO_MODEL_NAME = os.getenv("DASHSCOPE_VEO_MODEL_NAME", "wan2.6-t2v")
DASHSCOPE_API_KEY    = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL   = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

MOONSHOT_MODEL_NAME = os.getenv("MOONSHOT_MODEL_NAME", "kimi-k2-turbo-preview")
MOONSHOT_API_KEY    = os.getenv("MOONSHOT_API_KEY")
MOONSHOT_BASE_URL   = os.getenv("MOONSHOT_BASE_URL")

DEEPSEEK_MODEL_NAME = os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-reasoner")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL")

GLM_MODEL_NAME = os.getenv("GLM_MODEL_NAME", "glm-4.7")
GLM_API_KEY = os.getenv("GLM_API_KEY")
GLM_BASE_URL = os.getenv("GLM_BASE_URL")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")


