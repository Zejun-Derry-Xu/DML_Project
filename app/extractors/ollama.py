from app.extractors.openai_compatible import OpenAICompatibleExtractor


class OllamaExtractor(OpenAICompatibleExtractor):
    """Ollama exposes the OpenAI-compatible chat completion surface."""
