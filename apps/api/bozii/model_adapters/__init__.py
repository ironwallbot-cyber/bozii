from bozii.model_adapters.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ModelAdapter,
    ModelError,
    ModelInfo,
    ModelProtocolError,
    ModelUnavailableError,
    ToolCall,
    ToolSpec,
    Usage,
)
from bozii.model_adapters.factory import (
    ProviderHealth,
    adapter_for,
    check_provider,
    default_adapter,
    discover_models,
    get_adapter_for_model,
    resolve_api_key,
)
from bozii.model_adapters.mock import MockAdapter
from bozii.model_adapters.ollama import OllamaAdapter
from bozii.model_adapters.openai_compat import OpenAICompatAdapter
from bozii.model_adapters.router import SelectedModel, list_available_models, select_model

__all__ = [
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ModelAdapter",
    "ModelError",
    "ModelInfo",
    "ModelProtocolError",
    "ModelUnavailableError",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "ProviderHealth",
    "adapter_for",
    "check_provider",
    "default_adapter",
    "discover_models",
    "get_adapter_for_model",
    "resolve_api_key",
    "MockAdapter",
    "OllamaAdapter",
    "OpenAICompatAdapter",
    "SelectedModel",
    "list_available_models",
    "select_model",
]
