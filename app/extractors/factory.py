from app.config import Settings
from app.extractors.base import FactExtractor
from app.extractors.dashscope import resolved_base_url, resolved_model
from app.extractors.hybrid import RuleFirstFactExtractor
from app.extractors.ollama import OllamaExtractor
from app.extractors.openai_compatible import OpenAICompatibleExtractor


def build_extractor(settings: Settings) -> FactExtractor:
    if settings.llm_provider == "rules":
        return RuleFirstFactExtractor()
    if settings.llm_provider == "dashscope":
        provider: FactExtractor = OpenAICompatibleExtractor(
            base_url=resolved_base_url(settings),
            model=resolved_model(settings),
            api_key=settings.dashscope_api_key,
            timeout_seconds=settings.llm_timeout_seconds,
            disable_thinking=True,
        )
        return RuleFirstFactExtractor(provider)
    provider_class = (
        OllamaExtractor if settings.llm_provider == "ollama" else OpenAICompatibleExtractor
    )
    fallback = provider_class(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    return RuleFirstFactExtractor(fallback)
