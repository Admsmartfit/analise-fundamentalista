"""Fontes de notícias: Google News BR e feeds RSS (embutidos ou cadastrados pelo usuário)."""
import re
import email.utils
import urllib.parse
from typing import List, Dict, Any, Optional

import httpx
from bs4 import BeautifulSoup

from src.sources.base import DataSource, SourceResult, BROWSER_HEADERS, clean_ticker

MAX_ITENS = 6

# Palavras que não identificam a empresa (sobram no "nome curto" de Yahoo/Fundamentus)
_GENERICAS = {"CIA", "COMPANHIA", "BANCO", "GRUPO", "S.A.", "SA", "PN", "ON", "UNT", "N1", "N2", "NM",
              "PNA", "PNB", "HOLDING", "PARTICIPACOES", "BRASIL", "DO", "DE", "DA"}


def termos_empresa(ticker: str, ctx: Dict[str, Any]) -> List[str]:
    """Termos para buscar/filtrar notícias: o ticker e a 1ª palavra relevante do nome."""
    termos = [clean_ticker(ticker)]
    nome = (ctx or {}).get("nome") or ""
    for palavra in re.split(r"\s+", nome.upper()):
        p = palavra.strip(".,-")
        if len(p) >= 3 and p not in _GENERICAS and p != termos[0]:
            termos.append(p.title())
            break
    return termos


def _data_iso(pub: Optional[str]) -> Optional[str]:
    if not pub:
        return None
    try:
        return email.utils.parsedate_to_datetime(pub).date().isoformat()
    except Exception:
        return None


def parse_rss(content: bytes, fonte_padrao: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(content, "xml")
    itens = []
    for item in soup.find_all(["item", "entry"]):
        titulo = item.title.get_text(strip=True) if item.title else ""
        if not titulo:
            continue
        link_tag = item.find("link")
        link = (link_tag.get("href") or link_tag.get_text(strip=True)) if link_tag else ""
        src = item.find("source")
        fonte = src.get_text(strip=True) if src else fonte_padrao
        pub = item.find(["pubDate", "published", "updated"])
        itens.append({
            "titulo": titulo,
            "link": link,
            "data": _data_iso(pub.get_text(strip=True)) if pub else None,
            "fonte": fonte,
        })
    return itens


class GoogleNewsSource(DataSource):
    id = "google_news"
    nome = "Google News BR"
    categoria = "noticias"
    descricao = "Manchetes em português dos últimos 30 dias, buscando pelo ticker e pelo nome da empresa."
    site = "https://news.google.com"

    def _fetch(self, ticker, result: SourceResult):
        termos = termos_empresa(ticker, self.ctx)
        query = " OR ".join(f'"{t}"' for t in termos) + " when:30d"
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
               + "&hl=pt-BR&gl=BR&ceid=BR:pt-419")
        with httpx.Client(headers=BROWSER_HEADERS, timeout=self.timeout, follow_redirects=True) as client:
            resp = client.get(url)
        resp.raise_for_status()
        itens = parse_rss(resp.content, self.nome)[:MAX_ITENS]
        # Google acrescenta " - Veículo" ao título; o veículo já vai no campo "fonte"
        for it in itens:
            if it["fonte"] and it["titulo"].endswith(f" - {it['fonte']}"):
                it["titulo"] = it["titulo"][: -len(f" - {it['fonte']}")]
        result.itens = itens
        result.ok = bool(itens)
        result.resumo = f"{len(itens)} manchetes (busca: {', '.join(termos)})"
        if not itens:
            result.erro = "Nenhuma manchete encontrada nos últimos 30 dias."


class RSSSource(DataSource):
    """
    Feed RSS genérico.
    - Se a URL contém {ticker} ou {empresa}, é uma busca: o placeholder é substituído.
    - Se não contém, o feed inteiro é baixado e filtrado pelas manchetes que citam o ticker/empresa.
    """
    categoria = "noticias"

    def __init__(self, fonte_id: str, nome: str, url_template: str, descricao: str = "",
                 removivel: bool = True, settings=None):
        super().__init__(settings)
        self.id = fonte_id
        self.nome = nome
        self.url_template = url_template
        self.removivel = removivel
        self.descricao = descricao or (
            "Feed cadastrado pelo usuário. " +
            ("Busca pelo ativo na URL." if self._eh_busca() else "Filtra manchetes que citam o ativo.")
        )
        self.site = re.sub(r"(https?://[^/]+).*", r"\1", url_template)

    def _eh_busca(self) -> bool:
        return "{ticker}" in self.url_template or "{empresa}" in self.url_template

    def info(self):
        d = super().info()
        d["url_template"] = self.url_template
        return d

    def _fetch(self, ticker, result: SourceResult):
        termos = termos_empresa(ticker, self.ctx)
        empresa = termos[1] if len(termos) > 1 else termos[0]
        url = (self.url_template
               .replace("{ticker}", urllib.parse.quote(termos[0]))
               .replace("{empresa}", urllib.parse.quote(empresa)))
        with httpx.Client(headers=BROWSER_HEADERS, timeout=self.timeout, follow_redirects=True) as client:
            resp = client.get(url)
        resp.raise_for_status()
        itens = parse_rss(resp.content, self.nome)
        if not itens:
            result.erro = "O endereço respondeu, mas não parece ser um feed RSS/Atom válido."
            return

        if self._eh_busca():
            filtrados = itens
        else:
            padroes = [re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE) for t in termos]
            filtrados = [it for it in itens if any(p.search(it["titulo"]) for p in padroes)]

        result.itens = filtrados[:MAX_ITENS]
        result.ok = True  # feed respondeu; "0 manchetes" não é falha da fonte
        n = len(result.itens)
        result.resumo = (f"{n} {'manchete' if n == 1 else 'manchetes'} sobre o ativo"
                         + ("" if self._eh_busca() else f" (de {len(itens)} no feed)"))


# Feeds embutidos (podem ser desligados na tela, mas não removidos)
RSS_EMBUTIDOS = [
    ("infomoney", "InfoMoney", "https://www.infomoney.com.br/feed/",
     "Feed geral do InfoMoney, filtrado pelas manchetes que citam o ativo."),
    ("moneytimes", "Money Times", "https://www.moneytimes.com.br/feed/",
     "Feed geral do Money Times, filtrado pelas manchetes que citam o ativo."),
]
