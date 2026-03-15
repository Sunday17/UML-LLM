import json
import re
from openai import OpenAI
from utils.config import OPENAI_API_KEY, OPENAI_MODEL, BASE_URL

def openai_chat_completion(system_prompt: str, history: list, temperature=0, max_tokens=1500) -> str:
    """通用的 JSON 模式大模型调用接口"""
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=BASE_URL)
    messages = [
        {"role": "system", "content": system_prompt + " 你是一个只输出 JSON 的自动化接口。不要输出任何分析和解释"},
    ]
    messages.extend(history)
    
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={'type': 'json_object'} 
        )
        usage = response.usage
        print(f"[{OPENAI_MODEL}] 消耗: Prompt {usage.prompt_tokens}, Completion {usage.completion_tokens}")
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ LLM 调用异常: {e}")
        return "{}"