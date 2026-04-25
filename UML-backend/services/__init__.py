"""This file contains the services for the application."""

from services.database import database_service
from services.llm import (
    openai_chat_completion,
    openai_reasoning_completion,
)
from services.vector_store import vector_store

__all__ = [
    "database_service",
    "openai_chat_completion",
    "openai_reasoning_completion",
    "vector_store",
]


def __getattr__(name):
    """延迟导入 uml_service 以避免循环导入"""
    if name == "uml_service":
        from services.uml_service import uml_service
        return uml_service
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
