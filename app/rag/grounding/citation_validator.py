class CitationValidator:
    def validate(self, answer: str, sources: list[str]) -> bool:
        return bool(answer.strip()) and bool(sources)
