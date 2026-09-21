"""
auth.py — Autenticação OAuth2 com Google Sheets.
Rode UMA VEZ para autorizar o acesso:  python auth.py
O token fica salvo em .google_token.json para uso pelo app.
"""

from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR = Path(__file__).resolve().parent
CLIENT_SECRET = BASE_DIR / "client_secret_763787912262-j7hphqndsoqe3lurvekfqh934ls7suuv.apps.googleusercontent.com.json"
TOKEN_PATH = BASE_DIR / ".google_token.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def autenticar():
    print("=" * 60)
    print("  AUTENTICAÇÃO GOOGLE SHEETS — Fábrica de Achadinhos")
    print("=" * 60)
    print()

    if not CLIENT_SECRET.exists():
        print(f"ERRO: Arquivo não encontrado: {CLIENT_SECRET.name}")
        print("Baixe o JSON das credenciais OAuth2 no Google Cloud Console.")
        return False

    if TOKEN_PATH.exists():
        resp = input("Token já existe. Reautenticar? (s/N): ").strip().lower()
        if resp != "s":
            print("Mantendo token existente.")
            return True

    print("Abrindo navegador para autorização...")
    print("Se não abrir, copie o link abaixo e abra manualmente:\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)

    # run_local_server abre o navegador automaticamente
    creds = flow.run_local_server(port=8090)

    # salva o token
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"\n✅ Token salvo em: {TOKEN_PATH.name}")
    print("Agora o app pode ler e escrever na Google Sheets!")

    # teste rápido
    from googleapiclient.discovery import build
    service = build("sheets", "v4", credentials=creds)
    result = service.spreadsheets().values().get(
        spreadsheetId="1gckCWB0OzPQRgAMaMGj4J9wW48Ux8EDRcRNcRmR2Mq4",
        range="Produtos!A1:A2",
    ).execute()
    valores = result.get("values", [])
    print(f"\nTeste de leitura OK — {len(valores)} linhas lidas da planilha.")
    return True


if __name__ == "__main__":
    autenticar()
