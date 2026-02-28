# config.py
# 从环境变量读取全局配置，所有变量均有合理默认值
import os

# 大模型 API 密钥
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")

# API 基础 URL，支持切换至兼容 OpenAI 接口的国产模型端点
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")

# 使用的模型名称
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")

# 请求超时秒数
LLM_TIMEOUT_S: int = int(os.getenv("LLM_TIMEOUT_S", "60"))

# 排版模式：rule（纯规则）/ llm（纯大模型）/ hybrid（混合，推荐生产）
LLM_MODE: str = os.getenv("LLM_MODE", "hybrid")  # rule | llm | hybrid
