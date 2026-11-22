from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

HTTP_REQUESTS = Counter("http_requests_total", "Requests HTTP", ["method", "path", "status"])
HTTP_LATENCY = Histogram("http_request_duration_seconds", "Latência HTTP", ["method", "path"])
CHAT_QUESTIONS = Counter("rag_chat_questions_total", "Perguntas no chat", ["outcome"])
RETRIEVAL_LATENCY = Histogram("rag_retrieval_seconds", "Embedding da pergunta + busca vetorial")
LLM_FIRST_TOKEN = Histogram("rag_llm_first_token_seconds", "Tempo até o primeiro token do LLM")
RATE_LIMITED = Counter("rate_limited_total", "Requests barrados pelo rate limit", ["scope"])


def render() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
