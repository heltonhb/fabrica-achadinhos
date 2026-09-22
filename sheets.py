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
    produto_de_linha,
    salvar_csv_local,
    validar_ids_unicos,
)

logger = logging.getLogger(__name__)

ENV = carregar_env()

# ID da planilha (extraído da URL)
SPREADSHEET_ID = ENV.get(
    "GOOGLE_SHEETS_ID",
    "1gckCWB0OzPQRgAMaMGj4J9wW48Ux8EDRcRNcRmR2Mq4",
)
SHEET_NAME = ENV.get("GOOGLE_SHEET_NAME", "achados")  # aba da planilha
OAUTH_CLIENT_JSON = ENV.get("OAUTH_CLIENT_JSON", "")

# URL base para export CSV (leitura pública)
_EXPORT_URL = (
    f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv"
)

# ─── Google Sheets API (escrita via OAuth2) ──────────────────────────────────
_sheets_service = None
_TOKEN_PATH = BASE_DIR / ".google_token.json"


def _get_sheets_service():
    """Retorna serviço autenticado da Google Sheets API (OAuth2 desktop)."""
    global _sheets_service
    if _sheets_service is not None:
        return _sheets_service

    if not OAUTH_CLIENT_JSON:
        return None

    sa_path = Path(OAUTH_CLIENT_JSON).expanduser()
    if not sa_path.exists():
        logger.warning("OAUTH_CLIENT_JSON não encontrado: %s", sa_path)
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = None

        # tenta carregar token salvo
        if _TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), SCOPES)

        # se não tem token ou expirou, faz o fluxo OAuth
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(sa_path), SCOPES)
                # tenta local_server; se falhar (headless), usa console
                try:
                    creds = flow.run_local_server(port=0)
                except Exception:
                    creds = flow.run_console()
            # salva o token pra próximas vezes
            _TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
            logger.info("Token OAuth2 salvo em %s", _TOKEN_PATH)

        _sheets_service = build("sheets", "v4", credentials=creds)
        logger.info("Google Sheets API autenticada via OAuth2")
        return _sheets_service
    except Exception as exc:
        logger.error("Falha ao autenticar Google Sheets API: %s", exc)
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
