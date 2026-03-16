import os

# 实际生产中建议使用 dotenv 加载 .env 文件
# from dotenv import load_dotenv
# load_dotenv()

BASE_URL = os.getenv("BASE_URL", "https://api.deepseek.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-78382a2e62a8403f83013c5e4fd465d2")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "deepseek-chat")
REASONING_MODEL = os.getenv("REASONING_MODEL", "deepseek-reasoner")

# 大模型接口设置
# BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# OPENAI_API_KEY = "sk-2afc03925ef64192b0768cf09d0293dd"
# OPENAI_MODEL = "qwen3.5-plus"  # Default model