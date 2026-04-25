"""routers/v1/utils.py — 通用工具类 API。"""

import io
import os
import uuid
from datetime import datetime
from typing import BinaryIO, Dict, Any, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from utils import oss_client

router = APIRouter(prefix="/utils", tags=["Utils"])


def _now() -> datetime:
    """返回本地时间。"""
    return datetime.now()


def check_document_complexity(text: str, file_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    检测文档复杂度。

    复杂度判定规则：
    1. 文本长度超过 1200 字符
    2. PDF 文件包含图片

    返回:
        包含 is_complex 布尔值和建议信息的字典
    """
    is_complex = False
    reasons = []

    if len(text) > 1000:
        is_complex = True
        reasons.append(f"文本长度 {len(text)} 字符，超过 1200 字符阈值")

    if file_info and file_info.get("type") == "pdf":
        images_count = len(file_info.get("images", []))
        if images_count > 0:
            is_complex = True
            reasons.append(f"PDF 文档包含 {images_count} 张图片")

    suggestions = (
        "检测到文档内容复杂且可能包含多业务模块。直接生成可能会导致 UML 图表过于拥挤。"
        if is_complex else ""
    )

    return {
        "is_complex": is_complex,
        "suggestions": suggestions,
        "reasons": reasons,
    }


# --------------------------------------------------------------------------
# API 路由
# --------------------------------------------------------------------------


@router.post("/extract-text")
async def extract_text(file: UploadFile = File(...)):
    """
    将上传的文档（txt / pdf）转换为纯文本字符串，并检测复杂度。
    """
    suffix = os.path.splitext(file.filename or "")[-1].lower()
    content = file.file.read()
    bio = io.BytesIO(content)

    if suffix == ".pdf":
        text, file_info = _extract_pdf(io.BytesIO(content))
        file_url = oss_client.upload_file(bio, f"{uuid.uuid4().hex}{suffix}")
        complexity = check_document_complexity(text, file_info)
        return {
            "text": text,
            "is_complex": complexity["is_complex"],
            "suggestions": complexity["suggestions"],
            "file_url": file_url,
        }

    elif suffix == ".txt":
        text = _extract_txt_from_bytes(content)
        text_length = len(text)

        # 简单文本（<1000字）直接回填，不上传OSS
        if text_length < 1000:
            return {
                "text": text,
                "is_complex": False,
                "suggestions": "",
                "file_url": None,
            }

        # 复杂文本（>=1000字）上传OSS供RAG使用
        file_url = oss_client.upload_file(bio, f"{uuid.uuid4().hex}{suffix}")
        complexity = check_document_complexity(text, None)
        return {
            "text": text,
            "is_complex": complexity["is_complex"],
            "suggestions": complexity["suggestions"],
            "file_url": file_url,
        }

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {suffix}. Supported: .txt, .pdf",
        )


@router.post("/upload-file")
async def upload_file(file: UploadFile = File(...)):
    """
    纯上传接口：将文件上传至 OSS，返回 file_url。
    不做任何文本提取或复杂度检测。
    """
    suffix = os.path.splitext(file.filename or "")[-1].lower()
    content = file.file.read()
    bio = io.BytesIO(content)
    filename = f"{uuid.uuid4().hex}{suffix}"
    file_url = oss_client.upload_file(bio, filename)
    return {"file_url": file_url}


# --------------------------------------------------------------------------
# 内部提取函数
# --------------------------------------------------------------------------


def _extract_txt_from_bytes(raw: bytes) -> str:
    """读取 txt 文件（utf-8）并返回文本。"""
    try:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("gbk", errors="replace")
    except Exception as e:
        raise RuntimeError(f"Failed to read .txt file: {e}")


def _extract_pdf(stream: BinaryIO) -> tuple[str, Dict[str, Any]]:
    """
    读取 pdf 文件并提取所有页面的文本和图片信息。

    返回: (文本内容, 文件信息字典)
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError(
            "pdfplumber is not installed. Please run: pip install pdfplumber"
        )

    try:
        images = []
        with pdfplumber.open(stream) as pdf:
            pages_text = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
                page_images = page.images
                if page_images:
                    images.extend(page_images)

        text = "\n".join(pages_text)
        file_info = {
            "type": "pdf",
            "images": images,
        }
        return text, file_info
    except Exception as e:
        raise RuntimeError(f"Failed to parse .pdf file: {e}")
