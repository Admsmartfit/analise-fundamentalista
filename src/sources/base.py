"""
Contrato comum das Fontes de Dados.

Toda fonte (Yahoo, Fundamentus, CVM, RSS...) implementa `DataSource.fetch(ticker)`
e devolve um `SourceResult`. Assim o motor B3, a tela "Fontes de Dados" e o
resumo por ativo tratam qualquer fonte do mesmo jeito — incluir uma fonte nova
é só criar uma subclasse e registrá-la em `src/sources/registry.py`.
"""
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sources")

# Categorias usadas na tela e na consolidação dos dados
CATEGORIAS = {
    "fundamentos": "Fundamentos",
    "cotacao": "Cotação",
    "noticias": "Notícias",
    "regulatorio": "Regulatório (CVM)",
    "macro": "Macroeconomia",
}

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


def clean_ticker(ticker: str) -> str:
    return ticker.strip().upper().replace(".SA", "")


@dataclass
class SourceResult:
    fonte_id: str
    fonte_nome: str
    categoria: str
    ok: bool = False
    resumo: str = ""                                          # Uma linha legível para humanos
    dados: Dict[str, Any] = field(default_factory=dict)       # Dados estruturados (indicadores, macro...)
    itens: List[Dict[str, Any]] = field(default_factory=list) # Notícias / documentos: {titulo, link, data, fonte}
    avisos: List[str] = field(default_factory=list)           # Ex.: "DY 859% descartado (fora da faixa)"
    erro: Optional[str] = None
    latencia_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DataSource:
    """Classe base. Subclasses definem os atributos e implementam `_fetch`."""
    id: str = ""
    nome: str = ""
    categoria: str = "fundamentos"
    descricao: str = ""
    site: str = ""
    por_ativo: bool = True        # False para fontes de contexto (ex.: Selic/IPCA)
    removivel: bool = False       # True só para fontes cadastradas pelo usuário
    timeout: float = 12.0

    def __init__(self, settings: Optional[Dict[str, str]] = None):
        self.settings = settings or {}

    def _fetch(self, ticker: str, result: SourceResult) -> None:
        raise NotImplementedError

    def fetch(self, ticker: str, ctx: Optional[Dict[str, Any]] = None) -> SourceResult:
        """
        Executa a coleta medindo latência e sem nunca lançar exceção.
        `ctx` traz pistas já descobertas por outras fontes (ex.: {"nome": "PETROBRAS"})
        para fontes de notícias filtrarem pelo nome da empresa.
        """
        self.ctx = ctx or {}
        result = SourceResult(fonte_id=self.id, fonte_nome=self.nome, categoria=self.categoria)
        start = time.perf_counter()
        try:
            self._fetch(ticker, result)
        except Exception as e:  # Fonte fora do ar não pode derrubar a análise
            result.ok = False
            result.erro = f"{type(e).__name__}: {e}"[:400]
            logger.warning(f"[Fonte {self.id}] Falha para {ticker}: {result.erro}")
        result.latencia_ms = int((time.perf_counter() - start) * 1000)
        if not result.ok and not result.erro:
            result.erro = "Fonte não retornou dados para este ativo."
        return result

    def info(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "nome": self.nome,
            "categoria": self.categoria,
            "categoria_label": CATEGORIAS.get(self.categoria, self.categoria),
            "descricao": self.descricao,
            "site": self.site,
            "por_ativo": self.por_ativo,
            "removivel": self.removivel,
        }


def parse_br_number(text: str) -> Optional[float]:
    """Converte '1.234,56' / '8,5%' / '-1,16%' em float. Retorna None se vazio/inválido."""
    if text is None:
        return None
    t = text.strip().replace("%", "").replace("R$", "").strip()
    if not t or t in ("-", "--"):
        return None
    t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None
