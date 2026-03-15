from UCDAgent import UCDAgent
import os
import json

INPUT_FILE_PATH = "../datasets/test.txt"
file_name = os.path.basename(INPUT_FILE_PATH).split('.')[0]

os.makedirs("../output", exist_ok=True)
json_output_path = f"../output/{file_name}_result.json"
txt_output_path = f"../output/{file_name}_result.puml"

def main():
    if not os.path.exists(INPUT_FILE_PATH):
        print(f"❌ 找不到文件: {INPUT_FILE_PATH}")
        return

    with open(INPUT_FILE_PATH, "r", encoding='utf-8') as file:
        input_text = file.read().strip()
        
    print("🚀 启动自动化用例分析流水线 (Human-in-the-loop 模式)...")
    
    # 初始化
    UCD = UCDAgent(input_text)

    # ======== [阶段 1] 提取实体 ========
    extracted_data = UCD.extract_entities()
    
    if extracted_data:
        # 向用户展示提取的内容
        print("\n" + "="*40)
        print("🤖 AI 提取的实体结果:")
        print(json.dumps(extracted_data, indent=4, ensure_ascii=False))
        print("="*40 + "\n")
        
        # 询问用户是否需要修改
        choice = input("👉 是否需要修改提取的实体？(y/n) [默认 n]: ")
        
        if choice.strip().lower() == 'y':
            print("\n✏️ 请输入修改后的完整 JSON 数据。")
            print("💡 提示: 粘贴完代码后，在新的一行输入 'EOF' 并回车即可结束输入:")
            
            user_input = []
            while True:
                try:
                    line = input()
                    if line.strip() == 'EOF':
                        break
                    user_input.append(line)
                except EOFError:
                    break  # 支持 Ctrl+D / Ctrl+Z 结束
            
            corrected_json_str = "\n".join(user_input)
            
            # ======== [阶段 2] 应用用户修改 ========
            if corrected_json_str.strip():
                UCD.update_corrected_entities(corrected_json_str)
            else:
                print("⚠️ 输入为空，将继续使用原始提取结果。")
        else:
            print("⏭️ 跳过修改，使用原始提取结果。")

    # ======== [阶段 3] 提取关系并生成图表 ========
    UCD.extract_relationships()    # 基于确认过的实体，提取高级 UML 关系

    # 生成结果
    UCD.clean_redundant_relationships()
    UCD.save_to_json(json_output_path)
    UCD.generate_diagram(txt_output_path)
    
if __name__ == "__main__":
    main()