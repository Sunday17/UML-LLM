import os
import json
from graph.workflow import build_graph
from tools.generator import generate_usecase_outputs, generate_class_outputs

INPUT_FILE_PATH = "datasets/test.txt"

def handle_interrupt_and_resume(app, config):
    """处理断点拦截，并负责唤醒图引擎走完后续流程"""
    current_state_obj = app.get_state(config)
    state_values = current_state_obj.values
    next_nodes = current_state_obj.next
    
    if not next_nodes:
        return # 没有断点，直接结束

    # === 拦截：用例图 ===
    if "relationship_agent" in next_nodes:
        print("\n" + "="*40)
        print("🤖 [用例图] 提取的实体结果:")
        print(json.dumps(state_values.get("entities", {}), indent=4, ensure_ascii=False))
        choice = input("👉 是否需要修改【用例图】实体？(y/n) [默认 n]: ")
        if choice.strip().lower() == 'y':
            print("✏️ 请输入修改后的完整 JSON 数据 (一行输入 EOF 结束):")
            user_input = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if line.strip().upper() == "EOF":
                    break
                user_input.append(line)
            corrected_json_str = "\n".join(user_input).strip()
            corrected_entities = json.loads(corrected_json_str)
            actors = list(corrected_entities.keys())
            usecases = list({uc for ucs in corrected_entities.values() for uc in ucs})
            
            app.update_state(config, {
                "entities": corrected_entities, "actors": actors, "usecases": usecases
            })
            print("✅ 修正数据已更新！")

    # === 拦截：类图 ===
    elif "class_attr_method_agent" in next_nodes:
        print("\n" + "="*40)
        print("🤖 [类图] 提取的核心实体类:")
        print(json.dumps(state_values.get("classes", []), indent=4, ensure_ascii=False))
        choice = input("👉 是否需要修改【类图】实体类？(y/n) [默认 n]: ")
        if choice.strip().lower() == 'y':
            print("✏️ 请输入修改后的 JSON 列表 (例如 [\"User\", \"Habit\"]) (一行输入 EOF 结束):")
            user_input = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if line.strip().upper() == "EOF":
                    break
                user_input.append(line)
            corrected_json_str = "\n".join(user_input).strip()
            app.update_state(config, {"classes": json.loads(corrected_json_str)})
            print("✅ 修正数据已更新！")

    # 恢复运行（无论是否修改，都必须唤醒继续往下走）
    print("\n▶️ 触发后续 Agent，继续分析...")
    for event in app.stream(None, config):
        pass
    print("🎉 当前图表流转完毕！")


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
    
    print("🚀 欢迎使用 UML 自动化建模流水线！")
    
    while True:
        print("\n" + "-"*30)
        print("请选择要生成的图表任务：")
        print("1. 生成 用例图 (Use Case Diagram)")
        print("2. 生成 类图   (Class Diagram)")
        print("q. 退出程序")
        print("-"*30)
        
        choice = input("👉 请输入指令 (1/2/q): ").strip()
        
        if choice == 'q':
            print("👋 感谢使用，再见！")
            break
        elif choice == '1':
            target = "usecase"
        elif choice == '2':
            target = "class"
        else:
            print("⚠️ 无效输入，请重新选择。")
            continue
            
        print(f"\n🏃 开始执行 [{target}] 任务...")
        
        # 1. 注入目标指令并启动
        # 注意：这里会带着 input_text 进去。由于使用了同一个 thread_id，
        # LangGraph 会保留之前生成的数据（这正是我们想要的）
        for event in app.stream({"input_text": input_text, "current_diagram": target}, config):
            pass 
            
        # 2. 处理可能的人工断点，并让流水线跑到结束
        handle_interrupt_and_resume(app, config)
        
        # 3. 获取最新状态，生成对应产物
        final_state = app.get_state(config).values
        if target == "usecase":
            print("💾 正在保存用例图产物...")
            generate_usecase_outputs(final_state, "output", file_name)
        elif target == "class":
            print("💾 正在保存类图产物...")
            generate_class_outputs(final_state, "output", file_name)
if __name__ == "__main__":
    main()