import os
import json
from graph.workflow import build_graph
from tools.generator import generate_outputs

INPUT_FILE_PATH = "datasets/test.txt"

def main():
    if not os.path.exists(INPUT_FILE_PATH):
        print(f"❌ 找不到文件: {INPUT_FILE_PATH}")
        return

    file_name = os.path.basename(INPUT_FILE_PATH).split('.')[0]
    os.makedirs("output", exist_ok=True)
    json_output_path = f"output/{file_name}_result.json"
    txt_output_path = f"output/{file_name}_result.puml"

    with open(INPUT_FILE_PATH, "r", encoding='utf-8') as file:
        input_text = file.read().strip()
        
    print("🚀 启动 LangGraph 自动化分析流水线...")
    
    # 1. 编译并获取图实例
    app = build_graph()
    config = {"configurable": {"thread_id": "ucd_session_1"}}
    
    # 2. 运行直到遇到断点 (interrupt_before="relationship_agent")
    for event in app.stream({"input_text": input_text}, config):
        pass 
        
    # 3. 拦截：人工校验
    current_state = app.get_state(config).values
    
    print("\n" + "="*40)
    print("🤖 Agent 1 提取的实体结果:")
    print(json.dumps(current_state.get("entities", {}), indent=4, ensure_ascii=False))
    print("="*40 + "\n")
    
    choice = input("👉 是否需要修改提取的实体？(y/n) [默认 n]: ")
    
    if choice.strip().lower() == 'y':
        print("\n✏️ 请输入修改后的完整 JSON 数据。新的一行输入 'EOF' 并回车结束:")
        user_input = []
        while True:
            try:
                line = input()
                if line.strip() == 'EOF': break
                user_input.append(line)
            except EOFError:
                break
        
        corrected_json_str = "\n".join(user_input).strip()
        if corrected_json_str:
            try:
                corrected_entities = json.loads(corrected_json_str)
                actors = list(corrected_entities.keys())
                uc_set = set()
                for ucs in corrected_entities.values():
                    uc_set.update(ucs)
                
                # 【核心】写入覆盖状态
                app.update_state(config, {
                    "entities": corrected_entities, 
                    "actors": actors, 
                    "usecases": list(uc_set)
                })
                print("✅ 修正数据已更新至图状态！")
            except Exception as e:
                print(f"❌ 修正数据格式错误: {e}")
                
    # 4. 恢复图运行
    print("\n▶️ 触发 Agent 2: 继续分析逻辑关系...")
    for event in app.stream(None, config):
        pass
        
    # 5. 生成结果
    final_state = app.get_state(config).values
    generate_outputs(final_state, json_output_path, txt_output_path)

if __name__ == "__main__":
    main()