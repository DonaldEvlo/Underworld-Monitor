from bs4 import BeautifulSoup, Comment

_REMOVE_TAGS = (
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "noscript",
    "svg",
    "aside",
)


class RobustExtractor:
    """HTML -> texte exploitable. Isole le texte utile (titre, corps, liens) et ne
    lève jamais d'exception : un document illisible doit être mis de côté par
    l'appelant, pas faire échouer toute la collecte."""

    def extract(self, raw_html: str) -> dict:
        try:
            soup = BeautifulSoup(raw_html, "lxml")
        except Exception:
            soup = BeautifulSoup(raw_html, "html.parser")

        for tag in soup.find_all(_REMOVE_TAGS):
            tag.decompose()
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        text = self._normalize_whitespace(soup.get_text(separator=" "))
        links = [a["href"] for a in soup.find_all("a", href=True)]

        return {
            "title": (
                soup.title.string.strip() if soup.title and soup.title.string else ""
            ),
            "text": text,
            "links": links,
            "raw_html": raw_html,
        }

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return " ".join(text.split())
