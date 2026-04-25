"""向量存储服务 - 基于 ChromaDB + Sentence-Transformers 的 RAG 实现。

功能：
1. 文本分块：使用 jieba 进行中文分词，按句子/段落切分
2. 向量化：使用 sentence-transformers 将文本转为向量
3. 存储检索：使用 ChromaDB 存储向量并支持相似度检索
"""

import os
import hashlib
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

import jieba
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# 向量模型配置（中文支持好的模型）
DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# ChromaDB 本地存储路径
CHROMA_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), ".chromadb"
)


@dataclass
class TextChunk:
    """文本分块"""
    id: str
    content: str
    metadata: Dict[str, Any]


class VectorStoreService:
    """向量存储服务 - 支持中文语义检索"""

    def __init__(
        self,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        persist_directory: str = CHROMA_DB_PATH,
    ):
        self.embedding_model_name = embedding_model
        self.persist_directory = persist_directory

        # 延迟初始化模型（避免启动时耗时）
        self._model: Optional[SentenceTransformer] = None

        # ChromaDB 客户端（持久化存储）
        self._client: Optional[chromadb.PersistentClient] = None

        # 当前项目的集合名（按项目隔离）
        self._current_collection: Optional[str] = None

    @property
    def model(self) -> SentenceTransformer:
        """延迟加载 Embedding 模型"""
        if self._model is None:
            logger.info(f"Loading embedding model: {self.embedding_model_name}")
            self._model = SentenceTransformer(self.embedding_model_name)
            logger.info("Embedding model loaded successfully")
        return self._model

    @property
    def client(self) -> chromadb.PersistentClient:
        """获取 ChromaDB 客户端"""
        if self._client is None:
            os.makedirs(self.persist_directory, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(anonymized_telemetry=False),
            )
        return self._client

    def _generate_chunk_id(self, project_id: int, chunk_index: int) -> str:
        """生成唯一的 chunk ID"""
        return f"proj_{project_id}_chunk_{chunk_index}"

    def _split_text_by_sentences(self, text: str, max_chunk_size: int = 500) -> List[str]:
        """按句子分块（中文友好）"""
        # 句子结束符
        delimiters = ['。', '！', '？', '；', '\n', '\r\n']
        chunks = []
        current_chunk = []

        for char in text:
            current_chunk.append(char)
            if char in delimiters and len(''.join(current_chunk)) >= 100:
                chunk_text = ''.join(current_chunk).strip()
                if chunk_text:
                    chunks.append(chunk_text)
                current_chunk = []

        # 处理剩余内容
        if current_chunk:
            remaining = ''.join(current_chunk).strip()
            if remaining:
                # 如果剩余内容太长，继续拆分
                if len(remaining) > max_chunk_size:
                    # 使用 jieba 分词后按长度拆分
                    words = list(jieba.cut(remaining))
                    sub_chunk = []
                    sub_len = 0
                    for word in words:
                        sub_chunk.append(word)
                        sub_len += len(word)
                        if sub_len >= max_chunk_size:
                            chunks.append(''.join(sub_chunk))
                            sub_chunk = []
                            sub_len = 0
                    if sub_chunk:
                        chunks.append(''.join(sub_chunk))
                else:
                    chunks.append(remaining)

        return [c for c in chunks if c and len(c) > 10]  # 过滤太短的

    def _generate_embedding(self, texts: List[str]) -> List[List[float]]:
        """生成文本向量"""
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    def index_text(
        self,
        text: str,
        project_id: int,
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> int:
        """将文本分块并索引到向量数据库

        Args:
            text: 原始需求文本
            project_id: 项目ID（用于隔离不同项目的数据）
            chunk_size: 每个分块的最大字符数
            overlap: 相邻分块的重叠字符数

        Returns:
            分块数量
        """
        collection_name = f"project_{project_id}"

        # 1. 文本分块
        chunks = self._split_text_by_sentences(text, max_chunk_size=chunk_size)
        logger.info(f"Text split into {len(chunks)} chunks")

        if not chunks:
            logger.warning("No valid chunks generated from text")
            return 0

        # 2. 生成向量
        embeddings = self._generate_embedding(chunks)

        # 3. 存储到 ChromaDB
        # 先删除旧集合（如果存在）
        try:
            self.client.delete_collection(name=collection_name)
            logger.info(f"Deleted existing collection: {collection_name}")
        except Exception:
            pass

        # 创建新集合
        collection = self.client.create_collection(
            name=collection_name,
            metadata={"project_id": str(project_id)},
        )

        # 准备批量插入数据
        ids = [
            self._generate_chunk_id(project_id, i)
            for i in range(len(chunks))
        ]
        metadatas = [
            {"chunk_index": i, "chunk_size": len(chunks[i])}
            for i in range(len(chunks))
        ]

        # 批量插入
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )

        logger.info(f"Indexed {len(chunks)} chunks for project {project_id}")
        self._current_collection = collection_name
        return len(chunks)

    def retrieve(
        self,
        query: str,
        project_id: int,
        top_k: int = 3,
        min_similarity: float = 0.3,
    ) -> List[str]:
        """检索与查询相关的文本块

        Args:
            query: 检索查询（通常是模块的需求描述）
            project_id: 项目ID
            top_k: 返回的最相关块数
            min_similarity: 最低相似度阈值

        Returns:
            相关文本块列表
        """
        collection_name = f"project_{project_id}"

        try:
            collection = self.client.get_collection(name=collection_name)
        except Exception as e:
            logger.warning(f"Collection not found for project {project_id}: {e}")
            return []

        # 1. 将查询向量化
        query_embedding = self._generate_embedding([query])[0]

        # 2. 检索最相似的向量
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        # 3. 解析结果
        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]

        # 4. 过滤并返回
        relevant_chunks = []
        for doc, distance in zip(documents, distances):
            # ChromaDB 的 distance 是欧氏距离，转换为相似度
            similarity = 1 - distance / 2  # 近似映射
            if similarity >= min_similarity:
                relevant_chunks.append(doc.strip())

        logger.info(
            f"Retrieved {len(relevant_chunks)} relevant chunks for query "
            f"(top_k={top_k}, min_similarity={min_similarity})"
        )
        return relevant_chunks

    def retrieve_with_context(
        self,
        module_requirements: str,
        project_id: int,
        top_k: int = 3,
    ) -> str:
        """检索并格式化为上下文字符串

        用于直接拼接到 LLM Prompt 中

        Args:
            module_requirements: 模块需求描述
            project_id: 项目ID
            top_k: 检索数量

        Returns:
            格式化的上下文字符串
        """
        chunks = self.retrieve(module_requirements, project_id, top_k)

        if not chunks:
            return ""

        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            context_parts.append(f"【参考段落 {i}】\n{chunk}")

        header = "=" * 50
        footer = "=" * 50

        return (
            f"{header}\n"
            f"[原始需求参考 - 以下是与当前模块相关的需求段落]\n"
            f"{header}\n"
            + "\n\n".join(context_parts)
            + f"\n{footer}\n"
        )

    def clear_project_index(self, project_id: int) -> bool:
        """清除指定项目的索引"""
        collection_name = f"project_{project_id}"
        try:
            self.client.delete_collection(name=collection_name)
            logger.info(f"Cleared index for project {project_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to clear index for project {project_id}: {e}")
            return False

    def get_collection_info(self, project_id: int) -> Optional[Dict[str, Any]]:
        """获取项目索引信息"""
        collection_name = f"project_{project_id}"
        try:
            collection = self.client.get_collection(name=collection_name)
            return {
                "name": collection_name,
                "count": collection.count(),
                "metadata": collection.metadata,
            }
        except Exception:
            return None


# 模块级单例
vector_store = VectorStoreService()
