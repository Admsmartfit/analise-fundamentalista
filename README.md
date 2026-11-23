# TradingAgents B3 & Cockpit Web (v8.0)

**Cérebro Estratégico Autorizador de Análise Fundamentalista para o Mercado Brasileiro (B3)**

Este projeto implementa integralmente as diretrizes do [PRD Consolidado Final (v8.0)](file:///c:/Users/ralan/programa/analise%20fundamentalista/prd_consolidado_v8_0.md). Ele atua como um autorizador fundamentalista 24/7 autônomo que trabalha em conjunto (via Webhooks bidirecionais) com um sistema de análise técnica externo.

---

## 🏛️ Estrutura Arquitetural

```
analise fundamentalista/
├── upstream/
│   └── TradingAgents/              # Núcleo oficial TauricResearch (Isolamento Absoluto)
├── src/
│   ├── auth/                       # Segurança: Login, JWT e Hash Bcrypt
│   ├── b3/
│   │   ├── yahoo_connector.py      # Cotações B3 (.SA) e benchmark (^BVSP)
│   │   └── data_engine.py          # Consolida as fontes, valida dados e aplica a Trava de Segurança
│   ├── sources/                    # Fontes de Dados plugáveis (ver seção "Fontes de Dados")
│   │   ├── base.py                 # Contrato DataSource / SourceResult
│   │   ├── market.py               # Fundamentus, Yahoo Finance, brapi.dev
│   │   ├── official.py             # CVM (fatos relevantes/comunicados) e Banco Central (Selic, IPCA, dólar)
│   │   ├── news.py                 # Google News BR e feeds RSS (embutidos ou cadastrados pela tela)
│   │   └── registry.py             # Registro, coleta em paralelo, saúde e teste das fontes
│   ├── llm/                        # Key Pool com Hot-Swap e Cascata de Modelos
│   │   ├── key_pool.py             # Pool de chaves (Gemini, Claude, DeepSeek, OpenAI, Groq)
│   │   ├── model_cascade.py        # Triagem rápida (Flash) vs Veredito Gestor (Avançado)
│   │   └── prompt_builder.py       # Injeção de dados B3 e memória Post-Mortem
│   ├── memory/                     # Aprendizado Contínuo (Settle-and-Reflect)
│   │   └── settle_reflect.py       # Reflexão da IA em WIN/LOSS e lições aprendidas
│   ├── queue/                      # Smart Queue assíncrona
│   │   ├── smart_queue.py          # Resposta imediata HTTP 200 ao robô técnico
│   │   └── worker.py               # Worker em lote controlado (2 papéis por vez)
│   ├── webhooks/                   # Comunicação de Saída
│   │   ├── typesafe.py             # Saída rígida TypeSafe/JSON (Inspirado em TradingAgents-Jev)
│   │   └── dispatcher.py           # Fila Outbox com retentativa exponencial e detecção de queda
│   ├── watchdog/                   # Watchdog Duplo (Upstream + Customizado)
│   │   └── dual_watchdog.py        # Monitor de novidades e auto-update seguro às 03:00 AM
│   ├── notifications/              # WhatsApp Evolution API
│   │   └── evolution_api.py        # Alertas restritos aos 3 eventos sistêmicos permitidos
│   └── web/                        # Cockpit Web em Tempo Real (Inspirado em crypto-cockpit)
│       ├── app.py                  # Servidor FastAPI com agendador e ciclo de vida
│       ├── api_routes.py           # Endpoints REST e Webhooks
│       ├── static/                 # Estilos Dark Mode modernos e Scripts SPA
│       └── templates/              # HTML do Cockpit e Tela de Login
├── main.py                         # Ponto de entrada (CLI e Servidor Web)
├── requirements.txt                # Dependências Python
├── pytest.ini                      # Configuração dos testes unitários
└── tests/                          # Suíte de testes automatizados (40 testes passando)
```

---

## ⚡ Funcionalidades Implementadas (PRD v8.0)

1. **Isolamento Absoluto (`upstream/TradingAgents`):**
   - Repositório oficial clonado e mantido limpo em `upstream/TradingAgents/`.
   - Toda a lógica brasileira, conectores da B3 e webhooks foram implementados na camada externa (`src/`).

2. **Fontes de Dados (aba "Fontes de Dados" do Cockpit):**

   | Fonte | Tipo | O que traz |
   |---|---|---|
   | Fundamentus | Fundamentos | P/L, P/VP, DY, ROE, ROIC, margens, dívida, liquidez (prioridade 1) |
   | Yahoo Finance | Fundamentos | Cotação e múltiplos (prioridade 2; notícias descartadas por serem irrelevantes) |
   | brapi.dev | Cotação | Cotação, variação do dia, faixa de 52 semanas (token opcional na tela) |
   | CVM – Dados Abertos | Regulatório | Fatos relevantes, comunicados, avisos e proventos dos últimos 45 dias, com link |
   | Banco Central (SGS) | Macro | Selic meta, IPCA 12m, dólar PTAX |
   | Google News BR, InfoMoney, Money Times | Notícias | Manchetes sobre o ativo (por ticker e nome da empresa) |

   - **Consolidação:** a primeira fonte (por prioridade) que traz cada indicador vence; valores fora de faixa
     plausível (ex.: DY > 40%) são descartados e geram aviso; divergência de cotação > 10% entre fontes também.
   - **Na tela:** status, latência e último resultado de cada fonte; botão **Testar** (uma fonte) e **Testar todas**
     (mostra o que a IA receberia); ligar/desligar; cadastrar feeds RSS sem código (`{ticker}`/`{empresa}` na URL
     para feeds de busca, ou feed geral filtrado pelo ativo).
   - **Por ação:** botão **Fontes** no Gerenciador B3 mostra as últimas 5 análises: o que cada fonte trouxe,
     a triagem de notícias e quem decidiu (modelo de IA ou regra de contingência, com o motivo).
   - **Nova fonte em código:** subclasse de `DataSource` em `src/sources/` + inclusão em `FONTES_EMBUTIDAS`.
   - **Trava de Segurança:** sem cotação/indicadores e sem notícias/documentos CVM ⇒ `pausa_analise`.
   - Arquivos da CVM ficam em cache em `data/cache/` (renovados a cada 12h / 7 dias).

3. **Key Pool & Cascata de Modelos:**
   - Cadastro dinâmico de múltiplas chaves (Gemini, Claude, DeepSeek, OpenAI, Groq).
   - Hot-Swap automático em caso de Rate Limit ou esgotamento de cota diária.
   - Triagem barata/rápida com Gemini Flash / DeepSeek e Veredito Gestor profundo.
   - Disparo de alerta crítico no WhatsApp caso todo o pool se esgote.

4. **Smart Queue & Webhooks TypeSafe:**
   - Endpoint `POST /api/queue/demand`: liberação do robô técnico em milissegundos com HTTP 200.
   - Worker em background processando em lotes controlados (2 ativos por vez).
   - Callback de decisão com tipagem rígida TypeSafe/JSON (`{"ativo": "PETR4", "status": "autorizado", "conviccao": 0.85, "validade_dias": 7, ...}`).
   - Fila de retentativa outbox com backoff exponencial e alerta em caso de queda consecutiva severa da infraestrutura.

5. **Memória de Aprendizado Contínuo (Settle-and-Reflect):**
   - Endpoint `POST /api/memory/feedback`: recebe encerramento de trade (WIN/LOSS e motivo gráfico).
   - A IA realiza reflexão pós-morte cruzando o motivo com a tese fundamentalista prévia.
   - Grava a "Lição Aprendida", que é automaticamente injetada no prompt da próxima avaliação do ativo.

6. **Watchdog Duplo:**
   - **Watchdog Upstream:** Detecta atualizações no repositório oficial da base e emite aviso visual no Cockpit + WhatsApp (atualização estritamente manual).
   - **Watchdog Customizado:** Detecta commits da adaptação brasileira, exibe aviso e agenda o auto-update para as 03:00 AM (fora do horário de pregão).

7. **Alertas WhatsApp Evolution API:**
   - Disparos restritos aos 3 eventos sistêmicos permitidos (Zero Spam):
     1. Esgotamento total do Key Pool.
     2. Alertas de Watchdog (Nova versão ou Auto-update às 03:00).
     3. Queda consecutiva severa de Webhooks com o robô técnico.

8. **Cockpit Web em Tempo Real:**
   - Interface dark mode moderna, inspirada em crypto-cockpit.
   - Login seguro com token JWT.
   - Tabela central B3 com status da tese resumida em PT-BR e barra de validade.
   - Barra de progresso da IA ao vivo e métricas da Smart Queue.
   - Gestão visual de chaves, webhooks outbox e memórias pós-morte.

---

## 🔌 Integração com o Robô Técnico

Especificação completa (o que enviar, o que receber, exemplos, reenvios e roteiro de teste):
[docs/INTEGRACAO_ROBO_TECNICO.md](docs/INTEGRACAO_ROBO_TECNICO.md)

---

## 💿 Instalador para Windows e Atualização pelo Cockpit

### Gerar o instalador (nesta máquina de desenvolvimento)
```
python build/build.py --notes "O que mudou nesta versão"
```
Gera em `dist/`:
| Arquivo | Para quê |
|---|---|
| `TradingAgentsB3-Setup-X.Y.Z.exe` (~53 MB) | **Instalador único**: leva Python embutido + dependências + sistema. Não precisa de Python no destino. |
| `TradingAgentsB3-app-X.Y.Z.zip` (~230 KB) | Pacote de atualização (só o código) |
| `latest.json` | Manifesto lido pelo botão **Atualizar** (versão, SHA-256, notas) |

O build roda toda a suíte de testes **dentro do Python embutido** e abre as páginas antes de empacotar.
Opções: `--channel <pasta|URL>` (já deixa o canal configurado no instalador), `--publish <pasta>`
(copia pacote + latest.json para o canal), `--include-db` (leva o banco atual com chaves e histórico;
não compartilhe esse instalador).

### Instalar no Windows de destino
Execute o `.exe` (se o Windows SmartScreen avisar, clique em *Mais informações → Executar assim mesmo*).
Ele pergunta senha do admin, porta, URL do robô e se deve iniciar com o Windows. Instala em
`%LOCALAPPDATA%\TradingAgentsB3` (sem precisar de administrador):

```
TradingAgentsB3\
├── runtime\   Python embutido + bibliotecas
├── app\       código (trocado pelas atualizações)
└── data\      .env, tradingagents.db, cache, backups\, logs\   ← nunca apagado por atualização
```
Cria atalho na Área de Trabalho/Menu Iniciar, início automático (opcional) e entrada em
*Aplicativos instalados* para desinstalar. Rodar um instalador novo por cima mantém os dados.

### Atualizar com um clique (canal: GitHub)
Canal configurado no Cockpit (**Watchdog & Ajustes → Atualização do Sistema → Canal**):
```
https://raw.githubusercontent.com/Admsmartfit/analise-fundamentalista/main/updates/latest.json
```
Para lançar uma versão nova:
1. Aumente o número em `VERSION` (ex.: `8.1.0` → `8.1.1`).
2. `python build/build.py --skip-installer --publish updates --notes "O que mudou"`
3. `git add -A && git commit -m "Versão 8.1.1" && git push`
4. No computador instalado: **Verificar** → **Atualizar** (o GitHub pode levar até 5 min para mostrar o arquivo novo).

O repositório é público: o `.gitignore` impede que banco (`*.db`, que guarda as chaves de API), `.env`,
`dist/` e o cache do build sejam enviados. Nunca force a inclusão desses arquivos.
Sem internet/GitHub, também funciona com uma pasta compartilhada como canal ou com **Atualizar com arquivo .zip**.

O que acontece ao clicar: baixa o pacote e confere o SHA-256 → backup do banco em `data\backups\` →
para o servidor → troca `app\` → instala dependências novas se `requirements.txt` mudou → reinicia.
Se a versão nova não subir, **volta sozinha para a anterior** (testado: ~10 s numa atualização normal,
~22 s num rollback). Detalhes em `data\logs\update.log`.

---

## 🚀 Como Executar

### 1. Iniciar o Cockpit Web e o Motor de Background
```bash
python main.py
# ou com parâmetros personalizados:
python main.py --host 0.0.0.0 --port 8000
```
- Acesse no navegador: `http://localhost:8000`
- Credenciais padrão:
  - **Usuário:** `admin`
  - **Senha:** `admin123`

### 2. Comandos CLI Úteis
- **Enfileirar ativos via terminal:**
  ```bash
  python main.py --enqueue PETR4,VALE3,ITUB4
  ```
- **Executar verificação manual do Watchdog:**
  ```bash
  python main.py --watchdog
  ```

### 3. Executar a Suíte de Testes
```bash
pytest tests/ -v
```
*(14 testes unitários cobrindo autenticação, fallback B3, key pool hot-swap, smart queue, memória pós-morte, webhooks typesafe e rotas de API).*
