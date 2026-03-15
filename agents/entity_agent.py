import json
from graph.state import UCDState
from utils.llm import openai_chat_completion
from prompts.templates import get_template

def extract_entities_node(state: UCDState) -> dict:
    """Agent 1: 负责从需求文本中提取角色和用例"""
    print("======== [Agent 1] 正在提取实体 ========")
    input_text = state["input_text"]
    
    fallback = "从文本中提取角色和用例，JSON格式输出：{{\"角色\":[\"用例\"]}}。文本：{input_text}"
    prompt_tpl = get_template("ee_template", fallback)

    prompt = prompt_tpl.format(input_text=input_text)
    system_msg = "你是一个 UML 需求分析助手。请将需求中的参与者和用例提取为 JSON 格式。"
    
    res = openai_chat_completion(
        system_prompt=system_msg, 
        history=[{"role": "user", "content": prompt}]
    )
    
    try:
        data = json.loads(res)
        actors = list(data.keys())
        uc_set = set()
        for ucs in data.values():
            uc_set.update(ucs)
        usecases = list(uc_set)
        
        print(f"✅ 实体提取成功: {len(actors)}角色 / {len(usecases)}用例")
        # 返回增量状态，LangGraph 会自动合并到全局 State 中
        return {"entities": data, "actors": actors, "usecases": usecases}
    except Exception as e:
        print(f"❌ 实体解析失败: {e}")
        return {"entities": {}, "actors": [], "usecases": []}