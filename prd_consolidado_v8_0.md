# PRD Consolidado Final (v8.0): TradingAgents B3 & Cockpit Web

## 1. Visão Geral e Diretrizes do Projeto
Este projeto implementa um sistema autônomo de inteligência artificial focado em análise fundamentalista, leitura de notícias e sentimento para o mercado brasileiro (B3). Ele atua como um "Cérebro Estratégico Autorizador", trabalhando em conjunto (via Webhooks) com um sistema de análise técnica externo que é soberano nas execuções gráficas. O sistema roda de forma contínua, sem intervenção manual (sem botão de pânico), operando via painel web para gestão e configuração visual.

**Premissas:**
*   **Isolamento Absoluto:** O núcleo original `TauricResearch/TradingAgents` permanecerá intocado na pasta `upstream/`. A sua lógica brasileira e de webhooks será construída por fora, puxando as dependências necessárias.
*   **Custo Otimizado de IA:** Todo o processamento de LLM será feito via APIs externas (Gemini, Claude, DeepSeek, etc.) maximizando chaves gratuitas e controlando gastos.
*   **Autonomia:** O sistema não requer supervisão diária. Alertas por WhatsApp são acionados apenas em eventos restritos e sistêmicos.

---

## 2. Arquitetura e Forks de Aceleração
Para poupar meses de trabalho e garantir estabilidade, o sistema utilizará as seguintes estruturas abertas (forks e projetos irmãos) como aceleradores arquiteturais:

1.  **Motor Web e UI em Tempo Real (Inspirado em `0x0funky/tradingagents-crypto`):**
    *   Fornecerá o arcabouço para o *Cockpit Web*. Todo o servidor web interno e o dashboard interativo que mostra a barra de progresso da IA processando os papéis ao vivo serão adaptados daqui.
2.  **Output Estruturado e Tipagem (Inspirado em `sushant-mishra-dtu/TradingAgents-Jev`):**
    *   Substitui a saída em texto livre das IAs por *TypeSafe/JSON Output*. Fundamental para garantir que o seu Webhook dispare para o robô técnico um formato rígido impossível de ser mal interpretado (Ex: `{"ativo":"PETR4", "status":"autorizado", "validade_dias":7}`).
3.  **Observabilidade de Custos e Estrutura de Corretora (Inspirado em `RMartires/ZTradingAgents`):**
    *   Uso de arquitetura de rastreamento de LLM para monitorar consumo financeiro exato de cada chave de API. A camada de segurança de tokens de corretora servirá de molde para a futura integração da XP Corretora.
4.  **Memória de Aprendizado Contínuo (Inspirado em `whitebirchio/trader`):**
    *   Implementação do conceito de *"Settle-and-reflect memory"*. O TradingAgents não apenas autoriza trades, mas recebe o resultado deles depois para aprender com os próprios acertos e erros (detalhado na seção 3.7).

---

## 3. Especificação Funcional do Produto

### 3.1. Watchdog Duplo (Atualização Segura)
O sistema monitora repositórios do GitHub continuamente, mas age de forma diferente para cada um:
*   **Watchdog das Fontes Originais:** Ao detectar atualizações na base oficial (`TauricResearch` ou dependências como `Antigravit`), o sistema **apenas avisa na tela** do Cockpit Web e emite notificação via WhatsApp. A atualização desta camada é sempre manual.
*   **Watchdog do Seu Sistema Customizado:** Quando você aprova/faz um *commit* no seu repositório de adaptação brasileira, o sistema exibe o aviso na tela e **agenda a reinstalação e o reinício automático do processo para as 03:00 AM**, blindando o horário de negociação (pregão).

### 3.2. Ecossistema B3 e Fontes de Dados (Sistema de Fallback)
O sistema opera nativamente com extensões `.SA` (B3) e benchmark Ibovespa (`^BVSP`).
*   **Fonte Primária:** Dados abertos e estruturados da CVM (balanços/Fatos Relevantes) e APIs gratuitas de cotação da B3/Yahoo Finance.
*   **Sequência de Fallback:** Se a API primária apresentar instabilidade, o sistema aciona rotinas de *web scraping* secundárias (StatusInvest ou Google News BR). 
*   **Trava de Segurança:** Se todas as fontes falharem para um ativo específico, ele recebe status de "Pausa de Análise" (bloqueio temporário por falta de confiabilidade nos dados).

### 3.3. Key Pool e Orçamento (Cascata de Modelos)
*   **Pool Automático:** O usuário cadastra dezenas de chaves de API. Quando uma chave atinge o limite (Rate Limit) ou cota financeira configurada, o sistema faz o "hot-swap" automático para a próxima chave, mantendo a fila andando.
*   **Cascata de Inteligência:** Modelos ágeis e baratos (ex: Gemini Flash) operam a triagem de notícias e leitura de PDFs da CVM. Apenas o "Agente Gestor" utiliza modelos avançados e de raciocínio profundo para emitir o veredito final.

### 3.4. Comunicação Bidirecional: A "Smart Queue"
Gestão assíncrona de webhooks para suportar o volume do robô técnico de forma fluida:
*   **Entrada de Demanda (Robô Técnico $\rightarrow$ TradingAgents):** O robô envia um array de ativos precisando de reavaliação.
*   **Resposta Imediata:** O TradingAgents responde em milissegundos com `HTTP 200 - Ativos na Fila`, liberando o robô técnico. O processamento ocorre em lotes controlados (ex: 2 papéis por vez).
*   **Callback de Decisão (TradingAgents $\rightarrow$ Robô Técnico):** Ao finalizar o processamento de um ativo, um webhook individual devolve o status, a convicção e os dias de validade da análise.
*   **Fila de Retentativa (Retry):** Caso o endpoint do robô técnico caia, as mensagens são guardadas em fila local com retentativa exponencial.

### 3.5. Cockpit Web (Segurança e Painel de Controle)
Interface de gestão local ou em nuvem.
*   **Camada de Segurança Obrigatória:** Tela inicial com Login/Senha e geração de Token de Sessão JWT para acesso seguro via servidor Linux na internet.
*   **Gerenciador B3:** Tabela central de comando com a lista de ativos vigiados, status da tese atual (resumida em PT-BR) e barra de validade da autorização.
*   **Configurações e Integrações:** Formulários visuais para gerir as URLs de Webhook, Key Pool, agendamento de análises e tetos orçamentários.

### 3.6. Alertas Inteligentes via WhatsApp (Evolution API)
Alertas integrados ao servidor Evolution API do usuário, disparados apenas em **eventos sistêmicos restritos** (zero spam):
*   Aviso crítico: Esgotamento total do Key Pool (todas as chaves atingiram o limite).
*   Avisos de Watchdog: Deteção de nova versão no `TauricResearch` ou agendamento de auto-update às 03:00.
*   Alerta de infraestrutura: Queda consecutiva severa da comunicação (webhooks) com o robô técnico.

### 3.7. Memória de Aprendizado Contínuo (Settle-and-Reflect)
Inspirado na arquitetura `whitebirchio`, o sistema constrói um histórico qualitativo de performance.
*   **Feedback de Execução:** Quando o sistema de análise técnica encerra um trade (atingindo *Take Profit* ou *Stop Loss*), ele envia um Webhook de volta para o TradingAgents: `{"ativo": "VALE3", "resultado": "LOSS", "motivo_grafico": "Rompimento falso"}`.
*   **Reflexão da IA (Post-Mortem):** Em *background*, a IA cruza esse resultado financeiro com a tese fundamentalista que ela havia aprovado. Ela gera uma "Lição Aprendida" e grava no banco de dados.
*   **Consulta Futura:** Na próxima vez que o sistema avaliar `VALE3`, o contexto dessa lição será carregado no prompt do Agente, permitindo que o sistema refine gradualmente seus filtros e crie parâmetros únicos por ativo baseados no histórico da conta.

---

## 4. Roadmap de Execução (Fases de Desenvolvimento)

*   **Fase 1: Fundação, Autenticação e Cockpit (Semanas 1-2)**
    *   Clonagem limpa do `TauricResearch/TradingAgents` em `upstream/`.
    *   Construção do servidor web base com Flask/FastAPI, tela de Login (JWT) e Banco de Dados (SQLite).
    *   Implementação do Dashboard em tempo real inspirado em `tradingagents-crypto`.
*   **Fase 2: Motor B3, Key Pool e TypeSafe (Semanas 3-4)**
    *   Construção do conector CVM/B3/Yahoo com lógica nativa de Fallback.
    *   Desenvolvimento do motor de *Key Pool* e extração em formato JSON restrito.
*   **Fase 3: Smart Queue e Webhooks de Decisão (Semanas 5-6)**
    *   API de recepção de fila, processamento assíncrono e disparos de *Callback* com retentativas.
*   **Fase 4: Memória Pós-Morte e Notificações (Semanas 7-8)**
    *   Criação da API de recepção de "Resultados de Trade" para gravar a Memória (Settle-and-reflect).
    *   Integração do Watchdog Duplo (incluindo o cronjob das 03:00).
    *   Conexão com a Evolution API para os três alertas de WhatsApp permitidos.
*   **Fase 5: Futura Integração XP Corretora**
    *   Injeção de coleta de dados *real-time* e reconciliação de custódia utilizando APIs institucionais ou Open Finance.