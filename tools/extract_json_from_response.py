import re
import json

# 假设 res 是原始返回的字符串
# res = openai_reasoning_completion(prompt)

def extract_json_from_response(res):
    """
    从响应字符串中提取JSON部分
    """
    # 方法1：使用正则表达式提取 ```json 和 ``` 之间的内容
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', res)
    if json_match:
        json_str = json_match.group(1)
    else:
        # 方法2：如果没有代码块标记，尝试找到第一个 { 和最后一个 } 之间的内容
        start = res.find('{')
        end = res.rfind('}') + 1
        if start != -1 and end > start:
            json_str = res[start:end]
        else:
            raise ValueError("未找到有效的JSON内容")
    
    # 去除可能的空白字符
    json_str = json_str.strip()
    return json_str

