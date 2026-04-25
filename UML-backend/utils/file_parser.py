"""文件解析工具：处理本地文件读取、Base64 转换、PDF 解析、格式转换。"""

import base64
import io
import os
from typing import Optional, List, Tuple

import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# 路径转换工具
# ---------------------------------------------------------------------------

def get_absolute_file_path(file_url_or_path: str) -> str:
    """
    将 URL 路径或相对路径转换为操作系统绝对路径。

    处理场景：
    - `/static/uploads/xxx.pdf`  →  backend/uploads/xxx.pdf
    - `C:\\Users\\...\\uploads\\xxx.pdf`  →  直接返回（已是绝对路径）

    Returns:
        操作系统绝对路径字符串。
    """
    # Windows 下 /xxx 被 isabs() 误判为绝对路径，需先剥离 /static/ 前缀
    stripped = file_url_or_path.lstrip("/")

    # 移除 /static/ 或 static/ 前缀（URL 路径常见格式）
    if stripped.startswith("static/"):
        stripped = stripped[len("static/") :]
    elif stripped.startswith("static\\"):
        stripped = stripped[len("static\\") :]

    # 检查是否为真正的 Windows 绝对路径（C:\ 或 \\UNC）
    is_windows_abs = (
        len(stripped) >= 2 and stripped[1] == ":"
    ) or stripped.startswith("\\\\")

    if is_windows_abs:
        return os.path.normpath(stripped)

    # 相对路径：以 backend 目录为基准构建绝对路径
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    absolute = os.path.join(backend_root, stripped)
    return os.path.normpath(absolute)


# ---------------------------------------------------------------------------
# Base64 转换函数
# ---------------------------------------------------------------------------

def encode_file_to_base64(file_path: str) -> Optional[str]:
    """
    将本地文件（图片或 PDF）转换为 Base64 Data URI 格式。

    Args:
        file_path: 文件的绝对路径或 URL 路径（如 /static/uploads/xxx.pdf）。

    Returns:
        Data URI 字符串（如 "data:image/png;base64,xxxx..."），
        文件不存在或不支持该格式时返回 None。
    """
    absolute_path = get_absolute_file_path(file_path)

    if not os.path.exists(absolute_path):
        print(f"[ERROR] File not found: {absolute_path}")
        return None

    ext = os.path.splitext(absolute_path)[-1].lower()

    # 图片格式：直接读取并转 Base64
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}:
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
        }
        mime_type = mime_map.get(ext, "application/octet-stream")
        try:
            with open(absolute_path, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
            print(f"[INFO] Image encoded: {absolute_path} ({len(data)} base64 chars)")
            return f"data:{mime_type};base64,{data}"
        except Exception as e:
            print(f"[ERROR] Failed to encode image: {e}")
            return None

    # PDF 格式：渲染首页为 PNG 再转 Base64
    if ext == ".pdf":
        try:
            doc = fitz.open(absolute_path)
            if doc.page_count == 0:
                print(f"[ERROR] PDF has no pages: {absolute_path}")
                doc.close()
                return None
            page = doc.load_page(0)  # 第一页
            pix = page.get_pixmap(dpi=150)
            png_bytes = pix.tobytes("png")
            doc.close()
            data = base64.b64encode(png_bytes).decode("utf-8")
            print(f"[INFO] PDF first page rendered: {absolute_path} ({len(data)} base64 chars)")
            return f"data:image/png;base64,{data}"
        except Exception as e:
            print(f"[ERROR] Failed to render PDF: {e}")
            return None

    print(f"[WARN] Unsupported file format for Base64: {ext}")
    return None


# ---------------------------------------------------------------------------
# 兼容性别名（旧函数名仍可用）
# ---------------------------------------------------------------------------

def encode_local_image_to_base64(file_path: str) -> Optional[str]:
    """兼容性别名，内部委托给 encode_file_to_base64。"""
    return encode_file_to_base64(file_path)


# ---------------------------------------------------------------------------
# 格式转换工具（PDF 转图片）
# ---------------------------------------------------------------------------

def pdf_to_images(
    pdf_bytes: bytes,
    dpi: int = 150,
    zoom: float = 1.5,
) -> Tuple[List[bytes], List[int]]:
    """
    将 PDF 每页渲染为 PNG 图片，返回 (图片字节列表, 页码列表)。

    使用 PyMuPDF (fitz) 在内存中渲染，不落本地磁盘。

    Args:
        pdf_bytes: PDF 文件原始字节。
        dpi:       输出分辨率，默认 150。
        zoom:      缩放系数，默认 1.5（配合 150dpi = 约 225ppi）。

    Returns:
        (png_bytes_list, page_number_list)
        例如: ([b'...png...', b'...png...'], [1, 2])
    """
    doc = fitz.open("pdf", pdf_bytes)
    pages = []
    page_nums = []

    for i in range(doc.page_count):
        page = doc[i]
        # 计算渲染尺寸：默认 72dpi * zoom，近似 dpi 效果
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        png_bytes = pix.tobytes("png")
        pages.append(png_bytes)
        page_nums.append(i + 1)

    doc.close()
    return pages, page_nums
