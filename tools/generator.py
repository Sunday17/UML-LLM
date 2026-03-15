import os
import json
from jinja2 import Environment, FileSystemLoader
from plantuml import PlantUML

# 模板目录配置
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates", "puml")

def _to_dict(pair_list):
    """将 [["A","B"]] 转为 {"A":["B"]} 格式，方便模板引擎遍历"""
    d = {}
    if pair_list:
        for p, c in pair_list:
            d.setdefault(p, []).append(c)
    return d

def render_plantuml_to_image(puml_code: str, img_path: str):
    """调用 PlantUML Server 将 puml 文本直接渲染为 png 图片 (修复 Windows GBK 编码问题)"""
    try:
        server = PlantUML(url='http://www.plantuml.com/plantuml/img/')
        print(f"⏳ 正在请求渲染图片: {os.path.basename(img_path)} ...")
        
        # 【修改点 1】直接传入内存中的代码字符串，获取服务器返回的图片字节流
        img_bytes = server.processes(puml_code)
        
        # 【修改点 2】用二进制写入模式 ("wb") 保存图片文件
        with open(img_path, "wb") as f:
            f.write(img_bytes)
            
        print(f"✅ 图片渲染成功: {img_path}")
    except Exception as e:
        print(f"❌ 图片渲染失败 ({os.path.basename(img_path)}): {e}")

def generate_outputs(state: dict, output_dir: str, file_name_prefix: str):
    """
    生成最终产物：当前版本仅实现用例图的 PlantUML 代码生成与图片渲染
    """
    rels = state.get("relationships", {})
    data_context = {
        "actors": state.get("actors", []),
        "usecases": state.get("usecases", []),
        "entities": state.get("entities", {}), 
        "relationships": {
            "inclusion": _to_dict(rels.get("include", [])),
            "extension": _to_dict(rels.get("extend", [])),
            "uc_gen": _to_dict(rels.get("uc_generalization", [])),
            "act_gen": _to_dict(rels.get("actor_generalization", [])),
            "association": state.get("entities", {}) 
        }
    }

    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, f"{file_name_prefix}_data.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data_context, f, indent=4, ensure_ascii=False)
    print(f"\n💾 结构化数据基座已保存: {json_path}")

    try:
        env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
        template_file = "usecase.puml.j2"
        template = env.get_template(template_file)
    except Exception as e:
        print(f"❌ 模板加载失败，请检查 {TEMPLATE_DIR}/{template_file} 是否存在。错误信息: {e}")
        return

    puml_path = os.path.join(output_dir, f"{file_name_prefix}_usecase.puml")
    img_path = os.path.join(output_dir, f"{file_name_prefix}_usecase.png")
    
    try:
        # 注入数据，渲染 PUML 代码
        puml_code = template.render(data_context)
        with open(puml_path, "w", encoding='utf-8') as f:
            f.write(puml_code)
        print(f"📄 [USECASE] PUML代码已生成: {puml_path}")
        
        # 【修改点 3】这里不再传文件路径 puml_path，而是直接传 puml_code 字符串
        render_plantuml_to_image(puml_code, img_path)
        
    except Exception as e:
        print(f"⚠️ [USECASE] 生成或渲染异常: {e}")

    print("\n🎉 自动化建模流水线 (用例图环节) 执行完毕！")