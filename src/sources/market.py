"""Fontes de cotação e indicadores fundamentalistas: Yahoo Finance, Fundamentus e brapi.dev."""
import httpx
from bs4 import BeautifulSoup

from src.b3.yahoo_connector import YahooConnector
from src.sources.base import DataSource, SourceResult, BROWSER_HEADERS, clean_ticker, parse_br_number


def _fmt(v, suffix="", dec=2):
    if v is None:
        return "-"
    return f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".") + suffix


class YahooSource(DataSource):
    id = "yahoo"
    nome = "Yahoo Finance"
    categoria = "fundamentos"
    descricao = "Cotação, setor e múltiplos (P/L, P/VP, ROE, DY, margens, EV/EBITDA) via yfinance."
    site = "https://finance.yahoo.com"

    def _fetch(self, ticker, result: SourceResult):
        data = YahooConnector().fetch_fundamental_data(ticker)
        if not data:
            result.erro = "Yahoo não retornou cotação para o ticker."
            return
        ind = data.get("indicadores", {})
        result.ok = True
        result.dados = {
            "nome": data.get("nome"),
            "setor": data.get("setor"),
            "preco_atual": data.get("preco_atual"),
            "indicadores": ind,
        }
        # Notícias do Yahoo são descartadas de propósito: vêm em inglês e,
        # para papéis da B3, majoritariamente sobre outras empresas.
        result.resumo = (
            f"R$ {_fmt(data.get('preco_atual'))} · P/L {_fmt(ind.get('PL'))} · "
            f"ROE {_fmt(ind.get('ROE_pct'), '%', 1)} · DY {_fmt(ind.get('DY_pct'), '%', 1)}"
        )


class FundamentusSource(DataSource):
    id = "fundamentus"
    nome = "Fundamentus"
    categoria = "fundamentos"
    descricao = "Indicadores fundamentalistas completos de ações da B3 (balanço mais recente processado)."
    site = "https://www.fundamentus.com.br"

    # Rótulo no site -> chave interna
    CAMPOS = {
        "Cotação": "preco_atual",
        "Empresa": "nome",
        "Setor": "setor",
        "Subsetor": "subsetor",
        "Últ balanço processado": "ultimo_balanco",
        "P/L": "PL",
        "P/VP": "PVP",
        "Div. Yield": "DY_pct",
        "ROE": "ROE_pct",
        "ROIC": "ROIC_pct",
        "Marg. Líquida": "Margem_Liquida_pct",
        "Marg. EBIT": "Margem_EBIT_pct",
        "Marg. Bruta": "Margem_Bruta_pct",
        "EV / EBITDA": "EV_EBITDA",
        "Dív Líq / Patrim": "Div_Liq_Patrimonio",
        "Liquidez Corr": "Liquidez_Corrente",
        "Cres. Rec (5a)": "Cresc_Receita_5a_pct",
        "LPA": "LPA",
        "VPA": "VPA",
        "Valor de mercado": "Valor_Mercado",
        "Vol $ méd (2m)": "Volume_Medio_2m",
    }
    TEXTO = {"nome", "setor", "subsetor", "ultimo_balanco"}

    def _fetch(self, ticker, result: SourceResult):
        papel = clean_ticker(ticker)
        url = f"https://www.fundamentus.com.br/detalhes.php?papel={papel}"
        with httpx.Client(headers=BROWSER_HEADERS, timeout=self.timeout, follow_redirects=True) as client:
            resp = client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser", from_encoding="iso-8859-1")

        valores = {}
        for td in soup.select("td.label"):
            label = td.get_text(strip=True).lstrip("?").strip()
            chave = self.CAMPOS.get(label)
            val_td = td.find_next_sibling("td")
            if not chave or not val_td or chave in valores:
                continue  # primeira ocorrência = dados dos últimos 12 meses
            raw = val_td.get_text(strip=True)
            valores[chave] = raw if chave in self.TEXTO else parse_br_number(raw)

        if valores.get("preco_atual") is None:
            result.erro = "Papel não encontrado no Fundamentus."
            return

        info_keys = ("preco_atual", "nome", "setor", "subsetor", "ultimo_balanco")
        indicadores = {k: v for k, v in valores.items() if k not in info_keys and v is not None}
        result.ok = True
        result.dados = {
            "nome": valores.get("nome"),
            "setor": valores.get("setor"),
            "subsetor": valores.get("subsetor"),
            "ultimo_balanco": valores.get("ultimo_balanco"),
            "preco_atual": valores.get("preco_atual"),
            "indicadores": indicadores,
        }
        result.itens = [{"titulo": f"Página do papel {papel}", "link": url, "fonte": self.nome}]
        result.resumo = (
            f"R$ {_fmt(valores.get('preco_atual'))} · P/L {_fmt(indicadores.get('PL'))} · "
            f"ROE {_fmt(indicadores.get('ROE_pct'), '%', 1)} · DY {_fmt(indicadores.get('DY_pct'), '%', 1)} · "
            f"Dív.Líq/PL {_fmt(indicadores.get('Div_Liq_Patrimonio'))} · balanço {valores.get('ultimo_balanco') or '-'}"
        )


class BrapiSource(DataSource):
    id = "brapi"
    nome = "brapi.dev"
    categoria = "cotacao"
    descricao = ("API brasileira de cotações da B3. Funciona sem token para alguns papéis; "
                 "cadastre um token gratuito em brapi.dev para cobrir todos.")
    site = "https://brapi.dev"

    def _fetch(self, ticker, result: SourceResult):
        papel = clean_ticker(ticker)
        params = {}
        token = (self.settings.get("brapi_token") or "").strip()
        if token:
            params["token"] = token
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(f"https://brapi.dev/api/quote/{papel}", params=params)
        if resp.status_code in (401, 403):
            result.erro = f"HTTP {resp.status_code}: este papel exige token do brapi.dev (configure na tela de Fontes)."
            return
        resp.raise_for_status()
        res = (resp.json().get("results") or [{}])[0]
        preco = res.get("regularMarketPrice")
        if preco is None:
            result.erro = "brapi não retornou cotação."
            return
        var = res.get("regularMarketChangePercent")
        result.ok = True
        result.dados = {
            "nome": res.get("longName") or res.get("shortName"),
            "preco_atual": preco,
            "variacao_dia_pct": var,
            "min_52s": res.get("fiftyTwoWeekLow"),
            "max_52s": res.get("fiftyTwoWeekHigh"),
            "indicadores": {k: v for k, v in {
                "PL": res.get("priceEarnings"),
                "LPA": res.get("earningsPerShare"),
            }.items() if v is not None},
        }
        result.resumo = (
            f"R$ {_fmt(preco)} ({_fmt(var, '%')} no dia) · 52 sem: "
            f"{_fmt(res.get('fiftyTwoWeekLow'))} – {_fmt(res.get('fiftyTwoWeekHigh'))}"
        )
