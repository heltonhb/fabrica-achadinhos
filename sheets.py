"""
sheets.py — Porta única de leitura/escrita de produtos.

App, pipeline e webhook devem importar `ler_produtos` / `salvar_produtos`
daqui (não de config.py). Leitura: Google Sheets via export CSV público,
com fallback para o CSV local. Escrita: CSV local + sync por linha na
Google Sheets API (sem limpar a aba inteira).
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path

import requests

from config import (
    BASE_DIR,
    COLUNAS,
    CSV_PATH,
    Produto,
    carregar_env,
    ler_csv_local,
    obter_segredo,
    produto_de_linha,
    salvar_csv_local,
    validar_ids_unicos,
)

logger = logging.getLogger(__name__)

ENV = carregar_env()

# ID da planilha (extraído da URL)
SPREADSHEET_ID = (
    obter_segredo("GOOGLE_SHEETS_ID")
    or "1gckCWB0OzPQRgAMaMGj4J9wW48Ux8EDRcRNcRmR2Mq4"
)
SHEET_NAME = obter_segredo("GOOGLE_SHEET_NAME") or "Produtos"  # aba da planilha
# Token OAuth2 como conteúdo (secret/variável) — na nuvem não existe arquivo local
GOOGLE_TOKEN_JSON = obter_segredo("GOOGLE_TOKEN_JSON")
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# URL base para export CSV (leitura pública)
_EXPORT_URL = (
    f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv"
)

# ─── Google Sheets API (escrita via OAuth2) ──────────────────────────────────
_sheets_service = None
_TOKEN_PATH = BASE_DIR / ".google_token.json"


def _info_token() -> dict | None:
    """Token OAuth2 como dict: arquivo local `.google_token.json` ou
    conteúdo do secret/variável `GOOGLE_TOKEN_JSON` (nuvem)."""
    if _TOKEN_PATH.exists():
        try:
            return json.loads(_TOKEN_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Token local ilegível (%s); tentando secret", exc)

    valor = GOOGLE_TOKEN_JSON.strip()
    if not valor:
        return None
    if valor.startswith("{"):
        origem, bruto = "GOOGLE_TOKEN_JSON", valor
    else:
        caminho = Path(valor).expanduser()
        if not caminho.exists():
            logger.warning(
                "GOOGLE_TOKEN_JSON aponta para arquivo inexistente: %s", valor
            )
            return None
        try:
            origem, bruto = str(caminho), caminho.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Falha ao ler %s: %s", caminho, exc)
            return None
    try:
        return json.loads(bruto)
    except json.JSONDecodeError as exc:
        logger.warning("%s inválido: %s", origem, exc)
        return None


def _carregar_credenciais():
    """Credenciais válidas (renova token expirado), ou None (somente leitura).

    Sem fluxo OAuth interativo: um servidor headless não tem navegador.
    O caminho de (re)gerar o token é `python auth.py`, localmente.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    info = _info_token()
    if not info:
        return None
    try:
        creds = Credentials.from_authorized_user_info(info, _SCOPES)
    except (ValueError, KeyError) as exc:
        logger.warning("Token OAuth2 inválido: %s", exc)
        return None

    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception as exc:
            logger.warning("Falha ao renovar token OAuth2: %s", exc)
            return None
    logger.warning(
        "Token OAuth2 sem refresh_token válido — rode `python auth.py` "
        "localmente e, na nuvem, atualize o secret GOOGLE_TOKEN_JSON"
    )
    return None


def _get_sheets_service():
    """Retorna serviço autenticado da Google Sheets API (OAuth2 desktop)."""
    global _sheets_service
    if _sheets_service is not None:
        return _sheets_service

    try:
        creds = _carregar_credenciais()
    except ImportError:
        logger.warning("google-auth/google-api-client não instalados")
        return None
    if creds is None:
        return None

    try:
        from googleapiclient.discovery import build

        _sheets_service = build(
            "sheets", "v4", credentials=creds, cache_discovery=False
        )
        logger.info("Google Sheets API autenticada via OAuth2")
        return _sheets_service
    except Exception as exc:
        logger.error("Falha ao autenticar Google Sheets API: %s", exc)
        _sheets_service = None
        return None


def ler_produtos() -> list[Produto]:
    """Lê a planilha Google Sheets via export CSV público; fallback: CSV local."""
    try:
        resp = requests.get(_EXPORT_URL, timeout=15)
        resp.raise_for_status()
        texto = resp.text
    except Exception as exc:
        logger.warning("Falha ao ler Google Sheets: %s — usando CSV local", exc)
        return ler_csv_local(CSV_PATH)

    prods = []
    vistos: set[str] = set()
    for linha in csv.DictReader(io.StringIO(texto)):
        p = produto_de_linha(linha)
        if not p:
            continue
        if p.id in vistos:
            logger.warning("ID duplicado ignorado na leitura: %s", p.id)
            continue
        vistos.add(p.id)
        prods.append(p)
    logger.info("Lidos %d produtos da Google Sheets", len(prods))
    return prods


def salvar_produtos(prods: list[Produto]) -> None:
    """Valida IDs, grava CSV local e sincroniza por linha com o Google Sheets."""
    validar_ids_unicos(prods)
    salvar_csv_local(prods, CSV_PATH)
    logger.info("Salvos %d produtos em %s", len(prods), CSV_PATH)
    _sincronizar_para_sheets(prods)


def _linha_produto(p: Produto) -> list[str]:
    d = p.to_dict()
    return [d.get(col, "") for col in COLUNAS]


def _ler_valores_sheets(service) -> list[list[str]]:
    """Lê a aba atual via API (para mapear ID → número de linha)."""
    resp = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"'{SHEET_NAME}'")
        .execute()
    )
    return resp.get("values") or []


def _id_coluna(header: list[str]) -> int:
    for i, h in enumerate(header):
        if (h or "").strip() == "ID":
            return i
    return 0


def _mapa_id_linha(valores: list[list[str]], id_col: int) -> dict[str, int]:
    """Mapa ID → número de linha no Sheets (1-based; linha 1 = cabeçalho)."""
    mapa: dict[str, int] = {}
    for offset, row in enumerate(valores[1:], start=2):
        if len(row) > id_col:
            pid = (row[id_col] or "").strip()
            if pid and pid not in mapa:
                mapa[pid] = offset
    return mapa


def _sheet_id(service) -> int | None:
    meta = (
        service.spreadsheets()
        .get(spreadsheetId=SPREADSHEET_ID, fields="sheets.properties")
        .execute()
    )
    for s in meta.get("sheets", []):
        props = s.get("properties", {})
        if props.get("title") == SHEET_NAME:
            return props.get("sheetId")
    return None


def _sincronizar_para_sheets(prods: list[Produto]) -> bool:
    """Sync por linha: atualiza existentes, anexa novas, apaga removidas.

    Nunca limpa a aba inteira antes de escrever (evita perder dados se a
    chamada seguinte falhar).
    """
    service = _get_sheets_service()
    if not service:
        logger.debug("Google Sheets API indisponível — skip sync")
        return False

    try:
        valores = _ler_valores_sheets(service)

        # aba vazia → grava cabeçalho e sai (primeira escrita)
        if not valores:
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{SHEET_NAME}'!A1",
                valueInputOption="RAW",
                body={"values": [COLUNAS]},
            ).execute()
            valores = [COLUNAS]

        header = valores[0]
        id_col = _id_coluna(header)
        id_para_linha = _mapa_id_linha(valores, id_col)
        ids_novos = {p.id for p in prods}

        # 1. atualiza linhas existentes (um batchUpdate só)
        updates = []
        for p in prods:
            linha = id_para_linha.get(p.id)
            if linha is not None:
                updates.append(
                    {
                        "range": f"'{SHEET_NAME}'!A{linha}",
                        "values": [_linha_produto(p)],
                    }
                )
        if updates:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"valueInputOption": "RAW", "data": updates},
            ).execute()

        # 2. anexa produtos novos
        anexos = [_linha_produto(p) for p in prods if p.id not in id_para_linha]
        if anexos:
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{SHEET_NAME}'",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": anexos},
            ).execute()

        # 3. apaga linhas removidas (de baixo para cima, sem deslocar índice)
        remover = sorted(
            (ln for pid, ln in id_para_linha.items() if pid not in ids_novos),
            reverse=True,
        )
        if remover:
            sid = _sheet_id(service)
            if sid is None:
                logger.warning("Aba '%s' não encontrada — remoções não aplicadas", SHEET_NAME)
            else:
                service.spreadsheets().batchUpdate(
                    spreadsheetId=SPREADSHEET_ID,
                    body={
                        "requests": [
                            {
                                "deleteDimension": {
                                    "range": {
                                        "sheetId": sid,
                                        "dimension": "ROWS",
                                        "startIndex": ln - 1,  # 0-based
                                        "endIndex": ln,
                                    }
                                }
                            }
                            for ln in remover
                        ]
                    },
                ).execute()

        logger.info(
            "Sync Sheets: %d atualizados, %d anexados, %d removidos",
            len(updates),
            len(anexos),
            len(remover),
        )
        return True
    except Exception as exc:
        logger.error("Falha ao sincronizar Google Sheets: %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    prods = ler_produtos()
    for p in prods:
        print(f"{p.id} | {p.nome} | {p.status} | {p.gancho[:40]}...")
