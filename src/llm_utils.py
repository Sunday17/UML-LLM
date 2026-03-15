import json
import logging
import re
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL, BASE_URL

def openai_chat_completion(system_prompt: str, history: list, temperature=0, max_tokens=1500):
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=BASE_URL)
    
    # 强制 DeepSeek 只返回 JSON
    messages = [
        {"role": "system", "content": system_prompt + " 你是一个只输出 JSON 的自动化接口。不要输出任何分析和解释"},
    ]
    messages.extend(history)
    
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens, # 增加到 1500，防止截断
            # 【关键】：开启 DeepSeek 官方 JSON 模式
            response_format={'type': 'json_object'} 
        )
        
        content = response.choices[0].message.content
        usage = response.usage
        print(f"--- LLM 消耗统计 ---")
        print(f"输入: {usage.prompt_tokens}, 输出: {usage.completion_tokens}")
        return content
    except Exception as e:
        print(f"DeepSeek 调用异常: {e}")
        return ""

def parse_json_response(raw_text: str):
    """提取文本中的第一个JSON对象并解析"""
    if not raw_text: return {}
    try:
        # 寻找第一个 { 和最后一个 }
        match = re.search(r'(\{.*\})', raw_text, re.DOTALL)
        if match:
            json_str = match.group(1)
            # 纠正可能出现的中文引号
            json_str = json_str.replace('“', '"').replace('”', '"')
            return json.loads(json_str)
        return json.loads(raw_text)
    except Exception as e:
        logging.error(f"JSON解析失败: {e}")
        return {}

def parse_raw_list_answers(raw_text: str):
    """
    从 LLM 输出中健壮地解析出 Python 列表。
    支持处理带有 Markdown 标签、解释性文字的输出。
    """
    if not raw_text or not isinstance(raw_text, str):
        return []

    try:
        # 1. 尝试直接提取 [ ] 及其内部内容
        match = re.search(r'(\[.*\])', raw_text, re.DOTALL)
        if match:
            list_str = match.group(1)
            # 替换常见的中文标点，防止 ast 解析失败
            list_str = list_str.replace('“', '"').replace('”', '"').replace("‘", "'").replace("’", "'")
            return ast.literal_eval(list_str)
        
        # 2. 如果正则没匹配到括号，尝试提取引号内的所有内容（保底方案）
        items = re.findall(r"['\"](.*?)['\"]", raw_text)
        if items:
            return items
            
    except Exception as e:
        logging.error(f"解析列表失败: {e}, 原始文本: {raw_text}")
    
    return []

def parse_json_response(raw_text: str):
    """
    从 LLM 输出中提取并解析 JSON 对象。
    专门用于合并提取后的角色-用例映射以及关系提取。
    """
    if not raw_text:
        return {}

    try:
        # 提取第一个 { 到最后一个 } 之间的内容
        match = re.search(r'(\{.*\})', raw_text, re.DOTALL)
        if match:
            json_str = match.group(1)
            return json.loads(json_str)
        else:
            return json.loads(raw_text)
    except Exception as e:
        logging.error(f"解析JSON失败: {e}")
        return {}

def parse_raw_tuple(raw_tuple: str):
    """
    从字符串中提取元组内容，如 "(Parent, Child)"。
    """
    match = re.search(r'\((.*?)\)', raw_tuple)
    if match:
        content = match.group(1)
        items = [item.strip().strip("'\"") for item in content.split(',')]
        if len(items) == 2:
            return (items[0], items[1])
    return None