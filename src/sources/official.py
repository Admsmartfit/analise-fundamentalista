"""Fontes oficiais: CVM (dados abertos) e Banco Central (SGS)."""
import csv
import io
import time
import datetime
import threading
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

from src.config import CACHE_DIR
from src.sources.base import DataSource, SourceResult, clean_ticker
_lock = threading.Lock()
_mem: Dict[str, Tuple[float, object]] = {}  # caminho -> (mtime, índice já processado)


def _baixar_cache(url: str, nome: str, ttl_horas: float, timeout: float) -> Optional[Path]:
    """Baixa o arquivo para data/cache se não existir ou estiver vencido."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / nome
    with _lock:
        fresco = path.exists() and (time.time() - path.stat().st_mtime) < ttl_horas * 3600
        if not fresco:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url)
            if resp.status_code == 404:
                return path if path.exists() else None
            resp.raise_for_status()
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(resp.content)
            tmp.replace(path)
    return path


def _ler_csv_zip(path: Path, contem: str) -> List[Dict[str, str]]:
    with zipfile.ZipFile(path) as z:
        nome = next(n for n in z.namelist() if contem in n)
        texto = z.read(nome).decode("latin-1")
    return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


def _indice_cacheado(path: Path, construir):
    mtime = path.stat().st_mtime
    hit = _mem.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    indice = construir(path)
    _mem[str(path)] = (mtime, indice)
    return indice


class CVMSource(DataSource):
    id = "cvm"
    nome = "CVM – Dados Abertos"
    categoria = "regulatorio"
    descricao = ("Fatos relevantes, comunicados ao mercado, avisos aos acionistas e proventos "
                 "entregues à CVM nos últimos 45 dias, com link para o documento oficial.")
    site = "https://dados.cvm.gov.br"
    timeout = 60.0

    BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"
    CATEGORIAS = {
        "Fato Relevante",
        "Comunicado ao Mercado",
        "Aviso aos Acionistas",
        "Relatório Proventos",
        "Dados Econômico-Financeiros",
    }
    JANELA_DIAS = 45

    def _mapa_tickers(self, ano: int) -> Dict[str, Dict[str, str]]:
        path = _baixar_cache(f"{self.BASE}/FCA/DADOS/fca_cia_aberta_{ano}.zip",
                             f"fca_{ano}.zip", ttl_horas=24 * 7, timeout=self.timeout)
        if not path:
            return {}

        def construir(p):
            mapa = {}
            for r in _ler_csv_zip(p, "valor_mobiliario"):
                cod = (r.get("Codigo_Negociacao") or "").strip().upper()
                if cod:
                    mapa[cod] = {"cnpj": r["CNPJ_Companhia"], "empresa": r["Nome_Empresarial"],
                                 "segmento": r.get("Segmento") or ""}
            return mapa
        return _indice_cacheado(path, construir)

    def _documentos(self, ano: int) -> Dict[str, List[Dict[str, str]]]:
        path = _baixar_cache(f"{self.BASE}/IPE/DADOS/ipe_cia_aberta_{ano}.zip",
                             f"ipe_{ano}.zip", ttl_horas=12, timeout=self.timeout)
        if not path:
            return {}

        def construir(p):
            por_cnpj: Dict[str, List[Dict[str, str]]] = {}
            for r in _ler_csv_zip(p, "ipe_cia_aberta"):
                if r.get("Categoria") in self.CATEGORIAS:
                    por_cnpj.setdefault(r["CNPJ_Companhia"], []).append({
                        "data": r["Data_Entrega"], "categoria": r["Categoria"],
                        "tipo": r.get("Tipo") or "", "assunto": r.get("Assunto") or "",
                        "link": r.get("Link_Download") or "",
                    })
            return por_cnpj
        return _indice_cacheado(path, construir)

    def _fetch(self, ticker, result: SourceResult):
        papel = clean_ticker(ticker)
        hoje = datetime.date.today()
        anos = [hoje.year, hoje.year - 1]

        cadastro = None
        for ano in anos:
            cadastro = self._mapa_tickers(ano).get(papel)
            if cadastro:
                break
        if not cadastro:
            result.erro = f"{papel} não encontrado no cadastro de valores mobiliários da CVM (FCA)."
            return

        corte = (hoje - datetime.timedelta(days=self.JANELA_DIAS)).isoformat()
        docs = []
        for ano in anos if hoje.timetuple().tm_yday <= self.JANELA_DIAS else anos[:1]:
            docs += [d for d in self._documentos(ano).get(cadastro["cnpj"], []) if d["data"] >= corte]
        docs.sort(key=lambda d: d["data"], reverse=True)

        fatos = [d for d in docs if d["categoria"] == "Fato Relevante"]
        # Fatos relevantes primeiro (os mais importantes), depois os demais por data
        outros = [d for d in docs if d["categoria"] != "Fato Relevante"]
        docs = fatos + outros
        result.ok = True
        result.dados = {
            "empresa": cadastro["empresa"],
            "cnpj": cadastro["cnpj"],
            "segmento_listagem": cadastro["segmento"],
            "qtd_documentos_45d": len(docs),
            "qtd_fatos_relevantes_45d": len(fatos),
        }
        result.itens = [{
            "titulo": f"[{d['categoria']}] {d['assunto'] or d['tipo']}",
            "link": d["link"], "data": d["data"], "fonte": "CVM",
        } for d in docs[:8]]
        result.resumo = (f"{cadastro['empresa']} · {cadastro['segmento'] or 'segmento n/d'} · "
                         f"{len(docs)} documentos em {self.JANELA_DIAS} dias ({len(fatos)} fatos relevantes)")


class BCBMacroSource(DataSource):
    id = "bcb"
    nome = "Banco Central (SGS)"
    categoria = "macro"
    descricao = "Selic meta, IPCA acumulado 12 meses e dólar PTAX — contexto macro para a decisão."
    site = "https://www3.bcb.gov.br/sgspub"
    por_ativo = False

    SERIES = {
        "selic_meta_pct": (432, "Selic meta"),
        "ipca_12m_pct": (13522, "IPCA 12m"),
        "dolar_ptax": (10813, "Dólar PTAX"),
    }
    _cache: Dict[str, object] = {}
    TTL = 6 * 3600

    def _fetch(self, ticker, result: SourceResult):
        hit = self._cache.get("v")
        if hit and time.time() - hit[0] < self.TTL:
            dados = hit[1]
        else:
            dados = {}
            hoje = datetime.date.today()
            with httpx.Client(timeout=self.timeout, headers={"Accept": "application/json",
                                                             "Cache-Control": "no-cache"}) as client:
                for chave, (serie, _) in self.SERIES.items():
                    # Janela de datas em vez de /ultimos/1 (que às vezes responde 304 vazio)
                    resp = client.get(
                        f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados",
                        params={"formato": "json",
                                "dataInicial": (hoje - datetime.timedelta(days=400)).strftime("%d/%m/%Y"),
                                "dataFinal": hoje.strftime("%d/%m/%Y")})
                    if resp.status_code != 200:
                        continue
                    pontos = resp.json()
                    if pontos:
                        dados[chave] = float(pontos[-1]["valor"])
                        dados[chave + "_data"] = pontos[-1]["data"]
            if dados:
                self._cache["v"] = (time.time(), dados)

        if not dados:
            result.erro = "API do Banco Central não respondeu."
            return
        result.ok = True
        result.dados = dados
        partes = []
        for chave, (_, rotulo) in self.SERIES.items():
            if chave in dados:
                v = dados[chave]
                partes.append(f"{rotulo} {v:.2f}%" if chave.endswith("_pct") else f"{rotulo} R$ {v:.4f}")
        result.resumo = " · ".join(partes).replace(".", ",")
