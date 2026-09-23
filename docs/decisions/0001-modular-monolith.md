# ADR 0001: Modular monolith with deterministic policy

Status: Accepted

ReturnFlow begins as one FastAPI application with domain, extractor, service, repository, and API
boundaries. A deterministic Python policy engine owns all return decisions. Language models only
extract explicitly stated facts. This keeps the first release deployable and auditable without the
operational and consistency costs of microservices or multiple agents.

