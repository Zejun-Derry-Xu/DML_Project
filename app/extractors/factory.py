from app.config import Settings
from app.extractors.base import FactExtractor
from app.extractors.hybrid import HybridExtractor
from app.extractors.ollama import OllamaExtractor
from app.extractors.openai_compatible import OpenAICompatibleExtractor


def build_extractor(settings: Settings) -> FactExtractor:
    if settings.llm_provider == "rules":
        return HybridExtractor()
    provider_class = (
        OllamaExtractor if settings.llm_provider == "ollama" else OpenAICompatibleExtractor
    )
    provider = provider_class(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    return HybridExtractor(provider)
