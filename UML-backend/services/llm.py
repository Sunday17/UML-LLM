import io
import json
import re
import time
import os
import uuid
import atexit
import tempfile
from openai import AsyncOpenAI, OpenAI

from core.config import settings
from utils.file_parser import (
    encode_local_image_to_base64,
    pdf_to_images,
)
from utils import oss_client


# ---------------------------------------------------------------------------
# 临时图片文件清理
# ---------------------------------------------------------------------------
_oss_temp_images: list[str] = []


def _register_temp_cleanup(oss_key: str) -> None:
    """注册一个需要清理的 OSS Key，在进程退出时统一删除。"""
    _oss_temp_images.append(oss_key)


def _cleanup_temp_images() -> None:
    """进程退出时删除所有临时生成的图片文件（本地+OSS）。"""
    for key in _oss_temp_images:
        try:
            oss_client.delete_file(key)
            print(f"[CLEANUP] Deleted temp OSS image: {key}")
        except Exception as e:
            print(f"[CLEANUP] Failed to delete temp OSS image {key}: {e}")


atexit.register(_cleanup_temp_images)


def openai_chat_completion(system_prompt: str, history: list, temperature=0, max_tokens=1500) -> str:
    """通用的 JSON 模式大模型调用接口"""
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.BASE_URL)
    messages = [
        {"role": "system", "content": system_prompt + " 你是一个只输出 JSON 的自动化接口。不要输出任何分析和解释"},
    ]
    messages.extend(history)

    try:
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        usage = response.usage
        print(f"[{settings.OPENAI_MODEL}] usage: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}")
        return response.choices[0].message.content
    except Exception as e:
        print(f"[ERROR] LLM call failed: {e}")
        raise


def openai_reasoning_completion(prompt: str, max_tokens=10000) -> str:
    """专为推理大模型（如 deepseek-reasoner）设计的调用接口"""
    start_time = time.time()
    client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.BASE_URL)

    messages = [{"role": "user", "content": prompt}]

    try:
        response = client.chat.completions.create(
            model=settings.REASONING_MODEL,
            messages=messages,
            max_tokens=max_tokens,
        )
        usage = response.usage
        cost_time = time.time() - start_time
        print(f"[{settings.REASONING_MODEL}] usage: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}, time={cost_time:.2f}s")
        return response.choices[0].message.content
    except Exception as e:
        print(f"[ERROR] reasoning LLM call failed: {e}")
        raise


# ================================================================
# 文档解析工具（用于从 PDF 提取结构化文本）
# ================================================================

def _read_file_content(file_path: str) -> bytes:
    """读取文件内容到内存。自动识别本地路径或 OSS Key。"""
    if file_path.startswith("uploads/"):
        signed_url = oss_client.get_signed_url(file_path, expire=3600)
        import requests
        resp = requests.get(signed_url, timeout=30)
        resp.raise_for_status()
        return resp.content
    else:
        with open(file_path, "rb") as f:
            return f.read()


def _parse_pdf(file_path: str) -> str:
    """读取 PDF 文件，返回页面文本（保留页面分隔）。支持本地路径和 OSS Key。

    注意：对于扫描件/图片型 PDF（无文字层），此方法会返回空字符串。
    调用方应检测返回值长度，如果为 0 则说明 PDF 是扫描件。
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber not installed. Run: pip install pdfplumber")

    content = _read_file_content(file_path)
    bio = io.BytesIO(content)
    pages = []
    total_text_length = 0

    with pdfplumber.open(bio) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            text_len = len(text.strip())
            total_text_length += text_len
            if text.strip():
                pages.append(f"\n--- 第 {i} 页 ---\n{text}")

    if total_text_length < 50:
        # PDF 很可能是扫描件，没有可提取的文字层
        print(f"[WARN] PDF 可能是扫描件，提取到 {total_text_length} 字符文本")

    return "\n".join(pages)


def extract_structured_text(file_path: str) -> str:
    """根据文件类型调用对应解析器，返回结构化文本。支持本地路径和 OSS Key。"""
    if file_path.startswith("http"):
        from urllib.parse import urlparse
        ext = os.path.splitext(urlparse(file_path).path)[-1].lower()
    elif file_path.startswith("uploads/"):
        ext = os.path.splitext(file_path)[-1].lower()
    else:
        ext = os.path.splitext(file_path)[-1].lower()

    if ext == ".pdf":
        return _parse_pdf(file_path)
    elif ext == ".txt":
        content = _read_file_content(file_path)
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("gbk", errors="replace")
    else:
        raise RuntimeError(f"Unsupported file type for extraction: {ext}")


from core.prompts import SPLIT_SYSTEM_PROMPT, SPLIT_USER_PROMPT, PDF_EXTRACT_PROMPT


# ================================================================
# PDF 文本提取（使用 Qwen-VL 处理扫描件）
# ================================================================

async def extract_pdf_text_with_vl(
    file_path: str,
    max_images_per_batch: int = 5,
) -> str:
    """
    使用 Qwen-VL 从 PDF 中提取详细的文本描述（支持扫描件）。

    流程：
    1. 将 PDF 转换为图片
    2. 分批上传到 OSS 并获取签名 URL
    3. 使用 Qwen-VL-Plus 逐批提取文本
    4. 合并所有页面的文本

    Args:
        file_path: OSS Key（如 uploads/xxx.pdf）
        max_images_per_batch: 每批最大图片数（避免 token 溢出）

    Returns:
        所有页面的详细文本描述
    """
    from core.prompts import PDF_EXTRACT_PROMPT

    print(f"[PDF-VL] 开始从 PDF 提取文本: {file_path}")

    # 1. 读取 PDF 并转换为图片
    pdf_bytes = _read_file_content(file_path)
    pages, page_nums = pdf_to_images(pdf_bytes, dpi=150, zoom=1.5)
    print(f"[PDF-VL] PDF 转换完成，共 {len(pages)} 页")

    if not pages:
        print("[PDF-VL] PDF 没有页面，返回空")
        return ""

    # 2. 上传图片到 OSS
    image_urls = []
    for png_bytes, page_num in zip(pages, page_nums):
        oss_img_key = f"uploads/{uuid.uuid4().hex}_p{page_num}.png"
        bio = io.BytesIO(png_bytes)
        oss_client.upload_file(bio, oss_img_key)
        signed_url = oss_client.get_signed_url(oss_img_key, expire=3600)
        image_urls.append(signed_url)
        _register_temp_cleanup(oss_img_key)

    print(f"[PDF-VL] 已上传 {len(image_urls)} 张图片到 OSS")

    # 3. 分批使用 Qwen-VL 提取文本
    all_texts = []
    total_batches = (len(image_urls) + max_images_per_batch - 1) // max_images_per_batch

    client = AsyncOpenAI(
        api_key=settings.DASHSCOPE_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    for i in range(0, len(image_urls), max_images_per_batch):
        batch_urls = image_urls[i:i + max_images_per_batch]
        batch_num = i // max_images_per_batch + 1
        print(f"[PDF-VL] 处理第 {batch_num}/{total_batches} 批 ({len(batch_urls)} 张)...")

        # 构建 content_blocks
        content_blocks = [{"type": "image_url", "image_url": {"url": url}} for url in batch_urls]

        messages = [
            {"role": "system", "content": PDF_EXTRACT_PROMPT},
            {"role": "user", "content": content_blocks},
        ]

        try:
            response = await client.chat.completions.create(
                model="qwen-vl-plus",
                messages=messages,
                timeout=180.0,
                extra_body={"thinking_budget": 1024},
            )
            page_text = response.choices[0].message.content
            all_texts.append(page_text)
            print(f"[PDF-VL] 第 {batch_num} 批提取完成，文本长度: {len(page_text)} 字符")
        except Exception as e:
            print(f"[PDF-VL] 第 {batch_num} 批提取失败: {e}")
            all_texts.append(f"[第 {batch_num} 批提取失败]")

    result = "\n\n".join(all_texts)
    print(f"[PDF-VL] PDF 文本提取完成，总长度: {len(result)} 字符")
    return result


# ================================================================
# 分批处理配置
# ================================================================
# Qwen VL 模型单次最大处理的图片数量（保守估计，实际限额可能更高）
MAX_IMAGES_PER_BATCH = 10


def _merge_module_lists(results: list[dict]) -> dict:
    """
    合并多个模块列表，合并同名的模块，汇总 core_requirements。
    """
    module_map: dict[str, dict] = {}

    for result in results:
        for mod in result.get("modules", []):
            name = mod.get("module_name", "").strip()
            if not name:
                continue

            if name in module_map:
                existing_req = module_map[name].get("core_requirements", "")
                new_req = mod.get("core_requirements", "")
                if new_req and new_req not in existing_req:
                    module_map[name]["core_requirements"] = (
                        existing_req + "\n" + new_req
                    )
                existing_desc = module_map[name].get("description", "")
                new_desc = mod.get("description", "")
                if new_desc and new_desc not in existing_desc:
                    module_map[name]["description"] = existing_desc + " | " + new_desc
            else:
                module_map[name] = {
                    "module_name": name,
                    "description": mod.get("description", ""),
                    "core_requirements": mod.get("core_requirements", ""),
                }

    return {"modules": list(module_map.values())}


async def _vl_split(
    content_blocks: list,
    prompt_text: str = "",
) -> dict:
    """
    统一 VL 调用：接收已构建好的 content_blocks，发送 Qwen-VL-Plus 流式推理，
    返回归一化后的 {"modules": [...]} 字典。
    """
    client = AsyncOpenAI(
        api_key=settings.DASHSCOPE_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    # 构建消息：系统提示 + 用户消息（图片 + 文本提示）
    user_content = content_blocks.copy()
    if prompt_text:
        user_content.append({"type": "text", "text": prompt_text})

    messages = [
        {"role": "system", "content": SPLIT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    answer_content = ""

    try:
        stream = await client.chat.completions.create(
            model="qwen-vl-plus",
            messages=messages,
            stream=True,
            timeout=120.0,
            extra_body={"thinking_budget": 1024},
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                print(f"\033[94m[THINK] {reasoning}\033[0m", end="", flush=True)
            elif delta.content:
                answer_content += delta.content

    except Exception as e:
        print(f"\n[ERROR] Qwen VL call failed: {e}")
        raise

    print(f"\n\n===== [AI RAW STRING] =====\n{answer_content}\n================================\n")

    json_str = ""
    try:
        if answer_content.strip().startswith("{"):
            json_str = answer_content.strip()
        else:
            match = re.search(r"```json\s*(.*?)\s*```", answer_content, re.DOTALL)
            if match:
                json_str = match.group(1).strip()
        if not json_str:
            match = re.search(r"(\{.*\})", answer_content, re.DOTALL)
            if match:
                json_str = match.group(1).strip()
    except Exception:
        pass

    if not json_str:
        raise ValueError(
            f"JSON extraction failed. Raw response ({len(answer_content)} chars): {answer_content[:500]}"
        )

    try:
        result = json.loads(json_str)
        if "modules" in result:
            for mod in result["modules"]:
                cr = mod.get("core_requirements")
                if isinstance(cr, list):
                    mod["core_requirements"] = "\n".join(
                        str(item).strip() for item in cr if str(item).strip()
                    )
                elif cr is None:
                    mod["core_requirements"] = ""
        return result
    except json.JSONDecodeError as e:
        raise ValueError(
            f"JSON parse failed: {e}. Extracted string ({len(json_str)} chars): {json_str[:500]}"
        )


async def split_complex_project_with_qwen(
    text_content: str,
    file_path: str = None,
    process_mode: str = "auto",
) -> dict:
    """
    使用 Qwen-VL-Plus 对复杂需求进行模块拆分。

    处理流程（按 process_mode）：

    Returns:
        dict: 包含模块列表和提取文本的字典
            - {"modules": [...], "extracted_text": "PDF提取的文本"}
            - 拆分失败时返回 {"modules": [], "extracted_text": ""}
    """
    mode = process_mode
    oss_key = file_path
    ext = os.path.splitext(file_path or "")[-1].lower()
    is_image_ext = ext in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
    extracted_text = ""  # 用于存储 PDF 提取的文本

    # ------------------------------------------------------------------
    # 1. 根据模式决定 content_blocks
    # ------------------------------------------------------------------
    if mode == "vl_image" or (mode == "auto" and ext == ".pdf"):
        # PDF → 转 PNG 图片列表 → 上传 OSS → 签名 URL
        pdf_bytes = _read_file_content(file_path)
        pages, page_nums = pdf_to_images(pdf_bytes, dpi=150, zoom=1.5)

        print(f"[INFO] PDF 转图片完成，共 {len(pages)} 页")
        image_urls = []
        for png_bytes, page_num in zip(pages, page_nums):
            oss_img_key = f"uploads/{uuid.uuid4().hex}_p{page_num}.png"
            bio = io.BytesIO(png_bytes)
            oss_client.upload_file(bio, oss_img_key)
            signed_url = oss_client.get_signed_url(oss_img_key, expire=3600)
            image_urls.append(signed_url)
            _register_temp_cleanup(oss_img_key)
            print(f"[INFO] 第 {page_num} 页已上传 OSS: {oss_img_key}")

        content_blocks: list = [
            {"type": "image_url", "image_url": {"url": url}}
            for url in image_urls
        ]
        prompt_text = ""
        print(f"[INFO] VL 模式: PDF 图片 ({len(pages)} 页)")

    elif mode == "auto" and is_image_ext:
        signed_url = oss_client.get_signed_url(oss_key, expire=3600)
        content_blocks = [{"type": "image_url", "image_url": {"url": signed_url}}]
        prompt_text = ""
        print(f"[INFO] VL 模式: 图片直接传入")

    elif mode == "auto" and ext == ".txt":
        content_blocks = []
        prompt_text = SPLIT_USER_PROMPT.format(text_content=text_content)
        print("[INFO] 文本模式: TXT")

    elif mode == "vl_text":
        content_blocks = []
        prompt_text = SPLIT_USER_PROMPT.format(text_content=text_content)
        print("[INFO] 文本模式: vl_text 强制")

    else:
        content_blocks = []
        prompt_text = SPLIT_USER_PROMPT.format(text_content=text_content)
        print("[INFO] 文本模式: fallback（无文件或无法识别）")

    # ------------------------------------------------------------------
    # 1.5. PDF 模式：先用 Qwen-VL 提取完整文本（用于 RAG 存储）
    # ------------------------------------------------------------------
    if mode == "vl_image" or (mode == "auto" and ext == ".pdf"):
        # 调用 Qwen-VL 提取 PDF 完整文本
        print(f"[INFO] 开始从 PDF 提取详细文本（用于 RAG 存储）...")
        try:
            extracted_text = await extract_pdf_text_with_vl(file_path, max_images_per_batch=5)
            print(f"[INFO] PDF 文本提取完成，长度: {len(extracted_text)} 字符")
        except Exception as e:
            print(f"[WARN] PDF 文本提取失败: {e}，将继续拆分但不使用 RAG")
            extracted_text = ""

    # ------------------------------------------------------------------
    # 2. 调用 VL（PDF 模式支持分批处理，避免 token 溢出）
    # ------------------------------------------------------------------
    if not content_blocks and not prompt_text:
        raise ValueError(
            f"process_mode={mode}, ext={ext}, 无法构建 VL content_blocks。"
            "请检查文件类型是否支持。"
        )

    # PDF 分批处理
    if content_blocks and len(content_blocks) > MAX_IMAGES_PER_BATCH:
        print(f"[INFO] 图片数量 {len(content_blocks)} 超过限制 {MAX_IMAGES_PER_BATCH}，开始分批处理...")
        all_results = []
        total_batches = (len(content_blocks) + MAX_IMAGES_PER_BATCH - 1) // MAX_IMAGES_PER_BATCH
        for i in range(0, len(content_blocks), MAX_IMAGES_PER_BATCH):
            batch = content_blocks[i:i + MAX_IMAGES_PER_BATCH]
            batch_num = i // MAX_IMAGES_PER_BATCH + 1
            print(f"[INFO] 处理第 {batch_num}/{total_batches} 批图片 (共 {len(batch)} 张)")
            result = await _vl_split(batch, "")
            all_results.append(result)

        print(f"[INFO] 分批处理完成，共 {len(all_results)} 批，开始合并结果...")
        merged = _merge_module_lists(all_results)
        merged["extracted_text"] = extracted_text
        return merged

    result = await _vl_split(content_blocks, prompt_text)
    result["extracted_text"] = extracted_text
    return result
