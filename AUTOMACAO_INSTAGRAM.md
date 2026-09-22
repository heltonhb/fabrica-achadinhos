# 🤖 Guia de Automação do Instagram (Webhook Nativo)

Este documento explica como configurar e rodar o bot de automação do Instagram criado no arquivo `webhook_insta.py`. O objetivo desse bot é escutar os comentários dos seus Reels e enviar o link de afiliado por Direct Message (DM) automaticamente quando o usuário digitar uma palavra-chave (ex: "quero", "link").

---

## 1. Como Gerar o Token de Acesso da Conta Correta

Para que o bot consiga enviar mensagens em nome do seu Instagram, você precisa de um Token de Acesso da Graph API vinculado à conta oficial.

**Passo a passo:**
1. Acesse a [Ferramenta Explorador da Graph API da Meta](https://developers.facebook.com/tools/explorer/).
2. No menu lateral direito:
   * **Aplicativo Meta:** Selecione o seu App.
   * **Token de Acesso:** Troque de "Token do usuário" para o **Token da Página** (a página do Facebook vinculada ao seu Instagram Profissional).
3. Clique no botão **Adicionar permissões** e adicione exatamente estas:
   * `instagram_manage_comments` (Para o bot ler os comentários)
   * `instagram_manage_messages` (Para o bot conseguir enviar a DM)
   * `pages_show_list`
   * `pages_read_engagement`
4. Clique em **Generate Access Token** (Gerar token de acesso).
5. Autorize as permissões na janela pop-up que abrir.
6. Copie o token longo gerado.

---

## 2. Configurando as Variáveis (`.env`)

Abra o arquivo `.env` na raiz do projeto e preencha as variáveis com os dados que você acabou de gerar:

```env
# O token longo gerado no passo 1
INSTAGRAM_ACCESS_TOKEN=seu_token_aqui

# O ID da conta do Instagram (usado para o bot não responder a si mesmo)
INSTAGRAM_PAGE_ID=seu_id_aqui

# Uma senha inventada por nós apenas para validar a URL no painel da Meta
META_VERIFY_TOKEN=meu_token_secreto_123
```

---

## 3. Como Rodar e Testar Localmente

Como o painel do Streamlit e o Bot são aplicações diferentes, eles rodam em processos separados.

1. **Instale as dependências** (caso ainda não tenha feito):
   ```bash
   pip install fastapi uvicorn
   ```
2. **Inicie o servidor do Bot:**
   Abra um novo terminal e rode:
   ```bash
   python webhook_insta.py
   ```
   *O bot ficará rodando no endereço `http://localhost:8000`.*
3. **Exponha o bot para a Internet (com ngrok):**
   A Meta precisa de um link público (HTTPS) para enviar os avisos. Abra um terceiro terminal e rode:
   ```bash
   ngrok http 8000
   ```
   *Copie a URL HTTPS gerada pelo ngrok (ex: `https://abcd-123.ngrok-free.app`).*

---

## 4. Conectando o Bot ao Painel da Meta

Agora precisamos avisar à Meta para onde enviar os comentários.

1. Vá ao painel do [Meta for Developers](https://developers.facebook.com/) > Selecione seu App.
2. No menu lateral, clique em **Webhooks**.
3. Selecione a opção **Instagram** no menu suspenso.
4. Clique em **Subscribe to this object** (Assinar este objeto).
5. Preencha os dados:
   * **Callback URL:** A sua URL do ngrok + `/webhook` (ex: `https://abcd-123.ngrok-free.app/webhook`).
   * **Verify Token:** A senha que colocamos no `.env` (ex: `meu_token_secreto_123`).
6. Clique em **Verify and Save**.
7. Na lista que aparecer, clique em **Subscribe** ao lado dos campos `comments` e `messages`.

---

## 5. Próximos Passos no Código

No momento, o arquivo `webhook_insta.py` contém uma função chamada `buscar_link_por_media_id`. 

Como a Meta envia o ID do Post (`media_id`) quando alguém comenta, o próximo passo arquitetural seria salvar esse `media_id` no arquivo `achados.csv` sempre que o vídeo for postado. Dessa forma, o bot saberá exatamente qual link de afiliado puxar dependendo de qual vídeo a pessoa comentou "Quero". 

Atualmente, para fins de teste, ela está retornando um link fixo.
