"""阿里云 OSS 客户端封装，提供上传和签名 URL 生成能力。"""

import logging
import oss2

from core.config import settings

logger = logging.getLogger(__name__)


class OSSClient:
    _instance: "OSSClient | None" = None

    def __init__(self):
        auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
        self.bucket = oss2.Bucket(auth, settings.OSS_ENDPOINT, settings.OSS_BUCKET_NAME)
        logger.info(
            "OSSClient initialized",
            extra={
                "bucket": settings.OSS_BUCKET_NAME,
                "endpoint": settings.OSS_ENDPOINT,
            },
        )

    @classmethod
    def get_instance(cls) -> "OSSClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def upload_file(self, file_obj, file_key: str) -> str:
        """
        将 FastAPI 文件流直接上传到 OSS，返回 OSS 上的唯一 Key。

        Args:
            file_obj:  FastAPI UploadFile.file 流，或任意文件类对象。
            file_key:  OSS 上的目标 Key，以 "uploads/" 为前缀，如 "uploads/abc/doc.pdf"。
        Returns:
            OSS 文件 Key（file_key）。
        Raises:
            oss2.exceptions.OssError: 上传失败时抛出。
        """
        oss_key = file_key if file_key.startswith("uploads/") else f"uploads/{file_key}"
        # 统一转为 bytes 再上传，避免 BytesIO/file-like 对象触发 oss2 内部 filename 检测
        if hasattr(file_obj, "getvalue"):
            content = bytes(file_obj.getvalue())
        elif hasattr(file_obj, "read"):
            content = bytes(file_obj.read())
        else:
            content = bytes(file_obj)
        result = self.bucket.put_object(oss_key, content)
        if result.status == 200:
            logger.info(f"Upload succeeded: {oss_key}")
        else:
            logger.warning(f"Upload returned status {result.status}: {oss_key}")
        return oss_key

    def get_signed_url(self, oss_path: str, expire: int = 3600) -> str:
        """
        为私有 Bucket 中的文件生成带签名的临时访问 URL。

        Args:
            oss_path: OSS 上的文件路径。
            expire:   URL 有效期，单位秒，默认 1 小时。
        Returns:
            带签名的临时 URL。
        """
        url = self.bucket.sign_url("GET", oss_path, expire)
        logger.info(f"Signed URL generated for {oss_path}, expires in {expire}s")
        return url

    def delete_file(self, file_key: str) -> None:
        """
        从 OSS 彻底删除指定文件。

        Args:
            file_key: OSS 上的文件 Key。
        """
        self.bucket.delete_object(file_key)
        logger.info(f"Deleted from OSS: {file_key}")


# 全局单例，方便直接导入使用
oss_client = OSSClient.get_instance()
