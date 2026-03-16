import json
import re

def extract_json_from_text(text: str) -> dict:
    """
    从大模型返回的文本中提取并解析 JSON 数据。
    专为兼容 DeepSeek 推理模型、Gemini 设计：
    - 自动移除 ...
    - 自动提取 ```json 代码块
    - 自动截取 { ... } 最外层 JSON
    - 自动容错、不抛崩溃异常
    """
    # 1. 空值保护
    if not text or not isinstance(text, str):
        print("⚠️ 模型返回内容为空或不是字符串")
        return {}

    try:
        print(text)
        # 2. 移除 DeepSeek 推理思考标签 ...
        text_cleaned = re.sub(r'.*?', '', text, flags=re.DOTALL | re.IGNORECASE).strip()

        # 3. 移除 Markdown 代码块 ```json ... ```
        text_cleaned = re.sub(r'```[a-zA-Z0-9_]*\n?', '', text_cleaned)
        text_cleaned = text_cleaned.replace('```', '').strip()

        # 4. 【核心】暴力提取 最外层 { ... }
        start_idx = text_cleaned.find('{')
        end_idx = text_cleaned.rfind('}')

        if start_idx == -1 or end_idx == -1 or start_idx >= end_idx:
            print("⚠️ 未找到有效的 JSON 结构")
            return {}

        json_str = text_cleaned[start_idx:end_idx + 1].strip()

        # 5. 清理非法字符（防止解析失败）
        json_str = json_str.replace('\n', ' ').replace('\r', '')
        json_str = re.sub(r'\s+', ' ', json_str)

        # 6. 解析 JSON
        return json.loads(json_str)

    except json.JSONDecodeError as e:
        print(f"❌ JSON 格式错误: {str(e)}")
        return {}

    except Exception as e:
        print(f"❌ JSON 提取失败: {str(e)}")
        return {}