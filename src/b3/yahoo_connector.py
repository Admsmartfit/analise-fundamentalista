import logging
from typing import Dict, Any, Optional
import yfinance as yf

logger = logging.getLogger("b3.yahoo")

class YahooConnector:
    """
    Conector para cotações, múltiplos fundamentalistas e benchmark Ibovespa (^BVSP).
    Opera nativamente com sufixo .SA da B3.
    """
    def __init__(self):
        pass

    @staticmethod
    def normalize_ticker(ticker: str) -> str:
        """Garante que papéis da B3 tenham sufixo .SA (exceto índices como ^BVSP)"""
        ticker = ticker.strip().upper()
        if ticker.startswith("^"):
            return ticker
        if not ticker.endswith(".SA"):
            return f"{ticker}.SA"
        return ticker

    @staticmethod
    def dividend_yield_pct(info: Dict[str, Any]) -> float:
        """
        DY em %. O yfinance mudou o formato de `dividendYield`: hoje já vem em %
        (8.59 = 8,59%), antes vinha em fração. `trailingAnnualDividendYield`
        continua em fração, então é a referência preferida.
        """
        trailing = info.get("trailingAnnualDividendYield")
        if trailing is not None:
            return float(trailing) * 100.0
        dy = info.get("dividendYield")
        if dy is None:
            return 0.0
        return float(dy)  # formato atual do yfinance: já em %

    def fetch_fundamental_data(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Obtém múltiplos e demonstrações do Yahoo Finance.
        Retorna dicionário com P/L, ROE, Margens, DY e Notícias recentes.
        """
        symbol = self.normalize_ticker(ticker)
        try:
            stock = yf.Ticker(symbol)
            info = stock.info or {}
            
            # Se não houver dados válidos (ex: ticker incorreto ou bloqueio), retorna None
            if not info or ("regularMarketPrice" not in info and "currentPrice" not in info):
                logger.warning(f"[YahooConnector] Nenhum dado de mercado retornado para {symbol}")
                return None

            # Extração de múltiplos fundamentalistas chave
            preco = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
            pl = info.get("trailingPE") or info.get("forwardPE") or 0.0
            pvp = info.get("priceToBook") or 0.0
            roe = (info.get("returnOnEquity") or 0.0) * 100.0
            dy = self.dividend_yield_pct(info)
            ebitda_margin = (info.get("ebitdaMargins") or 0.0) * 100.0
            net_margin = (info.get("profitMargins") or 0.0) * 100.0
            ev_ebitda = info.get("enterpriseToEbitda") or 0.0
            nome = info.get("shortName") or info.get("longName") or symbol
            setor = info.get("sector") or info.get("industry") or "B3"

            # Notícias recentes
            news_items = []
            try:
                raw_news = stock.news or []
                for item in raw_news[:5]:
                    title = item.get("title") or item.get("content", {}).get("title")
                    if title:
                        news_items.append(title)
            except Exception:
                pass

            return {
                "fonte": "YahooFinance",
                "ticker": symbol,
                "nome": nome,
                "setor": setor,
                "preco_atual": round(preco, 2),
                "indicadores": {
                    "PL": round(pl, 2),
                    "PVP": round(pvp, 2),
                    "ROE_pct": round(roe, 2),
                    "DY_pct": round(dy, 2),
                    "Margem_Ebitda_pct": round(ebitda_margin, 2),
                    "Margem_Liquida_pct": round(net_margin, 2),
                    "EV_EBITDA": round(ev_ebitda, 2),
                },
                "noticias": news_items
            }
        except Exception as e:
            logger.warning(f"[YahooConnector] Erro ao buscar dados para {symbol}: {e}")
            return None

    def fetch_ibovespa_trend(self) -> Dict[str, Any]:
        """Obtém status e variação do benchmark Ibovespa (^BVSP)"""
        try:
            ibov = yf.Ticker("^BVSP")
            info = ibov.info or {}
            preco = info.get("regularMarketPrice") or info.get("currentPrice") or 0.0
            var_dia = (info.get("regularMarketChangePercent") or 0.0)
            return {
                "ticker": "^BVSP",
                "pontos": preco,
                "variacao_dia_pct": round(var_dia, 2)
            }
        except Exception as e:
            logger.warning(f"[YahooConnector] Falha ao consultar benchmark ^BVSP: {e}")
            return {"ticker": "^BVSP", "pontos": 0.0, "variacao_dia_pct": 0.0}
