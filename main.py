import os
import json
from graph.workflow import build_graph
from tools.generator import generate_usecase_outputs, generate_class_outputs, generate_sequence_outputs
from tools.puml_parser import sync_puml_to_state

INPUT_FILE_PATH = "datasets/test.txt"

def handle_interrupt_and_resume(app, config):
    """处理断点拦截，并负责唤醒图引擎走完后续流程"""
    current_state_obj = app.get_state(config)
    state_values = current_state_obj.values
    next_nodes = current_state_obj.next
    
    if not next_nodes:
        return 

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
                    if line.strip().upper() == "EOF": break
                    user_input.append(line)
                except EOFError: break
            corrected_json_str = "\n".join(user_input).strip()
            if corrected_json_str:
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
                    if line.strip().upper() == "EOF": break
                    user_input.append(line)
                except EOFError: break
            corrected_json_str = "\n".join(user_input).strip()
            if corrected_json_str:
                app.update_state(config, {"classes": json.loads(corrected_json_str)})
                print("✅ 修正数据已更新！")

    print("\n▶️ 触发后续 Agent，继续分析...")
    for event in app.stream(None, config):
        pass
    print("🎉 当前阶段 Agent 流转完毕！")


def wait_for_puml_edit_and_sync(app, config, target, puml_path):
    """等待用户在外部编辑器修改 PUML，然后逆向同步回 State"""
    print("\n" + "🌟"*20)
    print(f"[{target.upper()}] 产物已生成完毕！")
    print(f"📄 文件位置: {puml_path}")
    print("👉 如果大模型生成的属性或关系不符合预期，请直接在编辑器中修改该 .puml 文件。")
    print("👉 如果不需要修改，直接按回车跳过。")
    
    choice = input("修改完成后，输入 'y' 并回车同步数据 (直接回车表示不修改): ")
    
    if choice.strip().lower() == 'y':
        try:
            with open(puml_path, "r", encoding="utf-8") as f:
                modified_puml = f.read()
            
            current_state = app.get_state(config).values
            # 调用我们在上一阶段编写的逆向同步工具
            updated_fields = sync_puml_to_state(target, modified_puml, current_state)
            
            if updated_fields:
                app.update_state(config, updated_fields)
                print("✅ 逆向同步完成，最新的设计已写入全局记忆！")
        except Exception as e:
            print(f"❌ 读取或同步 PUML 失败: {e}")
    print("🌟"*20 + "\n")


def main():
    if not os.path.exists(INPUT_FILE_PATH):
        print(f"❌ 找不到文件: {INPUT_FILE_PATH}")
        return

    file_name = os.path.basename(INPUT_FILE_PATH).split('.')[0]
    os.makedirs("output", exist_ok=True)

    with open(INPUT_FILE_PATH, "r", encoding='utf-8') as file:
        input_text = file.read().strip()
        
    print("🚀 启动 LangGraph 自动化分析流水线...")
    app = build_graph()
    config = {"configurable": {"thread_id": "ucd_session_1"}}
    
    while True:
        print("\n" + "-"*40)
        print("请选择要生成的图表任务：")
        print("1. 生成 用例图 (Use Case)")
        print("2. 生成 类图   (Class)")
        print("3. 生成 时序图 (Sequence)")
        print("4. 自动生成全套 (用例 -> 类 -> 时序)")
        print("q. 退出程序")
        print("-" * 40)
        
        choice = input("👉 请输入指令 (1/2/3/4/q): ").strip()
        
        if choice == 'q':
            print("👋 感谢使用，再见！")
            break
            
        elif choice == '1': pipeline_tasks = ["usecase"]
        elif choice == '2': pipeline_tasks = ["class"]
        
        elif choice == '3':
            # ==========================================
            # 核心拦截逻辑：检查全局状态中是否已有前置图表数据
            # ==========================================
            current_state = app.get_state(config).values
            has_usecase = bool(current_state.get("usecases"))
            has_class = bool(current_state.get("classes"))
            
            if not (has_usecase and has_class):
                print("\n⚠️ 拦截：生成时序图必须依赖【用例图】和【类图】的数据！")
                print(f"📊 当前记忆状态 -> 用例数据: {'✅' if has_usecase else '❌'} | 类数据: {'✅' if has_class else '❌'}")
                print("💡 请先执行选项 1 和 2，或者直接选择选项 4 自动生成全套。")
                continue
            
            pipeline_tasks = ["sequence"]
            
        elif choice == '4':
            pipeline_tasks = ["usecase", "class", "sequence"]
        else:
            print("⚠️ 无效输入，请重新选择。")
            continue

        # 按顺序依次跑任务
        for target in pipeline_tasks:
            print(f"\n🏃 开始执行 [{target.upper()}] 任务...")
            
            # 1. 启动图引擎，注入指令
            for event in app.stream({"input_text": input_text, "current_diagram": target}, config):
                pass 
                
            # 2. 处理可能的人工断点 (仅用例和类图有)
            if target in ["usecase", "class"]:
                handle_interrupt_and_resume(app, config)
            
            # 3. 获取该阶段最终状态，并生成对应产物
            final_state = app.get_state(config).values
            puml_output_path = f"output/{file_name}_{target}.puml"
            
            if target == "usecase":
                generate_usecase_outputs(final_state, "output", file_name)
                wait_for_puml_edit_and_sync(app, config, "usecase", puml_output_path)
                
            elif target == "class":
                generate_class_outputs(final_state, "output", file_name)
                wait_for_puml_edit_and_sync(app, config, "class", puml_output_path)
                
            elif target == "sequence":
                # 时序图生成批量产物，无需逆向同步
                generate_sequence_outputs(final_state, "output", file_name)

if __name__ == "__main__":
    main()