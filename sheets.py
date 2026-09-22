"""
sheets.py — Integração com Google Sheets como fonte de dados.

Leitura via export CSV público.
Escrita via Google Sheets API (service account).
Configure SERVICE_ACCOUNT_JSON no .env com o caminho para o arquivo
de credenciais baixado do Google Cloud Console.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path

import requests

from config import BASE_DIR, COLUNAS, Produto, carregar_env

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
    """Lê a planilha Google Sheets via export CSV público."""
    try:
        resp = requests.get(_EXPORT_URL, timeout=15)
        resp.raise_for_status()
        texto = resp.text
    except Exception as exc:
        logger.warning("Falha ao ler Google Sheets: %s — usando CSV local", exc)
        return _ler_csv_local()

    reader = csv.DictReader(io.StringIO(texto))
    prods = []
    for linha in reader:
        p = Produto(
            id=(linha.get("ID") or "").strip(),
            status=(linha.get("Status") or "Ideia").strip(),
            data_postagem=(linha.get("Data Postagem") or "").strip(),
            nome=(linha.get("Nome do Produto") or "").strip(),
            nicho=(linha.get("Nicho") or "").strip(),
            preco=(linha.get("Preco Medio (R$)") or "").strip(),
            comissao=(linha.get("Comissao Est (R$)") or "").strip(),
            link_afiliado=(linha.get("Link Afiliado Shopee") or "").strip(),
            link_vitrine=(linha.get("Link Vitrine (Bio)") or "").strip(),
            pasta_midias=(linha.get("Pasta Midias") or "").strip(),
            gancho=(linha.get("Roteiro / Gancho") or "").strip(),
            post_agendado=(linha.get("Post Agendado") or "Nao").strip(),
            prompt_criativo=(linha.get("Prompt Criativo") or "").strip(),
            observacoes=(linha.get("Observacoes") or "").strip(),
            media_id_instagram=(linha.get("Media ID Instagram") or "").strip(),
            comentarios_quero=(linha.get("Comentarios QUERO") or "").strip(),
            alcance=(linha.get("Alcance") or "").strip(),
            salvamentos=(linha.get("Salvamentos") or "").strip(),
            nota_manual=(linha.get("Nota Manual") or "").strip(),
        )
        if p.id:
            prods.append(p)
    logger.info("Lidos %d produtos da Google Sheets", len(prods))
    return prods


def salvar_produtos(prods: list[Produto]) -> None:
    """Salva a lista de produtos no CSV local E sincroniza com Google Sheets."""
    # 1. CSV local (backup sempre)
    csv_path = BASE_DIR / "achados.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        for p in prods:
            w.writerow(p.to_dict())
    logger.info("Salvos %d produtos em %s", len(prods), csv_path)

    # 2. Google Sheets (se autenticado)
    _sincronizar_para_sheets(prods)


def _sincronizar_para_sheets(prods: list[Produto]) -> bool:
    """Escreve todos os produtos na Google Sheets (substitui a aba inteira)."""
    service = _get_sheets_service()
    if not service:
        logger.debug("Google Sheets API indisponível — skip sync")
        return False

    try:
        # monta as linhas: header + dados
        rows = [COLUNAS]
        for p in prods:
            d = p.to_dict()
            rows.append([d.get(col, "") for col in COLUNAS])

        # limpa a aba e escreve de uma vez
        range_name = f"'{SHEET_NAME}'!A1"
        service.spreadsheets().values().clear(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{SHEET_NAME}'",
            body={},
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()
        logger.info("Sincronizados %d produtos na Google Sheets", len(prods))
        return True
    except Exception as exc:
        logger.error("Falha ao sincronizar Google Sheets: %s", exc)
        return False


def _ler_csv_local() -> list[Produto]:
    """Fallback: lê o CSV local."""
    csv_path = BASE_DIR / "achados.csv"
    if not csv_path.exists():
        return []
    prods = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            p = Produto(
                id=(linha.get("ID") or "").strip(),
                status=(linha.get("Status") or "Ideia").strip(),
                data_postagem=(linha.get("Data Postagem") or "").strip(),
                nome=(linha.get("Nome do Produto") or "").strip(),
                nicho=(linha.get("Nicho") or "").strip(),
                preco=(linha.get("Preco Medio (R$)") or "").strip(),
                comissao=(linha.get("Comissao Est (R$)") or "").strip(),
                link_afiliado=(linha.get("Link Afiliado Shopee") or "").strip(),
                link_vitrine=(linha.get("Link Vitrine (Bio)") or "").strip(),
                pasta_midias=(linha.get("Pasta Midias") or "").strip(),
                gancho=(linha.get("Roteiro / Gancho") or "").strip(),
                post_agendado=(linha.get("Post Agendado") or "Nao").strip(),
                prompt_criativo=(linha.get("Prompt Criativo") or "").strip(),
                observacoes=(linha.get("Observacoes") or "").strip(),
                media_id_instagram=(linha.get("Media ID Instagram") or "").strip(),
                comentarios_quero=(linha.get("Comentarios QUERO") or "").strip(),
                alcance=(linha.get("Alcance") or "").strip(),
                salvamentos=(linha.get("Salvamentos") or "").strip(),
                nota_manual=(linha.get("Nota Manual") or "").strip(),
            )
            if p.id:
                prods.append(p)
    return prods


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    prods = ler_produtos()
    for p in prods:
        print(f"{p.id} | {p.nome} | {p.status} | {p.gancho[:40]}...")
