// TradingAgents B3 - Cockpit Web Frontend Logic (v8.0)
let currentTab = 'dashboard';
let pollInterval = null;

// Função utilitária para requisições com autenticação JWT
async function authFetch(url, options = {}) {
    const token = localStorage.getItem('tradingagents_token');
    if (!token && !url.includes('/api/auth/login')) {
        window.location.href = '/login';
        return;
    }

    options.headers = {
        ...options.headers,
        'Authorization': `Bearer ${token}`
    };

    const res = await fetch(url, options);
    if (res.status === 401) {
        localStorage.removeItem('tradingagents_token');
        window.location.href = '/login';
        return;
    }
    return res;
}

// Inicialização
document.addEventListener('DOMContentLoaded', () => {
    // Checa se está logado
    const token = localStorage.getItem('tradingagents_token');
    if (!token) {
        window.location.href = '/login';
        return;
    }

    initTabs();
    initForms();
    loadDashboardData();
    loadAssets();
    loadKeys();
    loadWebhooks();
    loadMemories();
    loadWatchdogs();
    loadLogs();

    // Polling contínuo em tempo real a cada 3.5 segundos para a Fila ao Vivo
    pollInterval = setInterval(() => {
        loadQueueStatusLive();
    }, 3500);
});

// Navegação de Abas
function initTabs() {
    const tabs = document.querySelectorAll('.nav-item');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const target = tab.getAttribute('data-tab');
            switchTab(target);
        });
    });
}

function switchTab(tabId) {
    currentTab = tabId;
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    const targetContent = document.getElementById(`tab-${tabId}`);
    if (targetContent) {
        targetContent.classList.add('active');
    }

    // Carrega dados frescos da aba
    if (tabId === 'assets') loadAssets();
    if (tabId === 'sources') { loadSources(); loadBrapiTokenStatus(); }
    if (tabId === 'keypool') loadKeys();
    if (tabId === 'smartqueue') loadWebhooks();
    if (tabId === 'memory') loadMemories();
    if (tabId === 'settings') { loadSettings(); loadUpdateStatus(); }
    if (tabId === 'logs') loadLogs();
}

// 1. Visão Geral e Fila ao Vivo
async function loadQueueStatusLive() {
    try {
        const res = await authFetch('/api/queue/status');
        if (!res || !res.ok) return;
        const data = await res.json();

        document.getElementById('stat-queued').innerText = data.aguardando || 0;
        document.getElementById('stat-processing').innerText = data.em_processamento || 0;
        document.getElementById('stat-completed').innerText = data.concluidos_hoje || 0;

        const liveBadge = document.getElementById('live-queue-badge');
        const progressBar = document.getElementById('live-progress-bar');
        const progressInfo = document.getElementById('current-processing-info');
        const progressPct = document.getElementById('progress-percentage');

        if (data.em_processamento > 0) {
            liveBadge.className = 'badge badge-warning';
            liveBadge.innerText = `Processando (${data.em_processamento})`;
            progressBar.style.width = '70%';
            progressInfo.innerText = `IA avaliando ativos em lote... (${data.aguardando} aguardando)`;
            progressPct.innerText = '70%';
        } else if (data.aguardando > 0) {
            liveBadge.className = 'badge badge-neutral';
            liveBadge.innerText = `Na Fila (${data.aguardando})`;
            progressBar.style.width = '25%';
            progressInfo.innerText = `Ativos na fila aguardando liberação do worker.`;
            progressPct.innerText = '25%';
        } else {
            liveBadge.className = 'badge badge-success';
            liveBadge.innerText = 'Fila Limpa';
            progressBar.style.width = '100%';
            progressInfo.innerText = 'Todos os papéis avaliados. Robô técnico liberado.';
            progressPct.innerText = '100%';
        }
    } catch (e) {
        console.error('Falha ao atualizar fila ao vivo:', e);
    }
}

async function loadDashboardData() {
    loadQueueStatusLive();
    loadQuickAssets();
}

async function loadQuickAssets() {
    try {
        const res = await authFetch('/api/assets');
        if (!res || !res.ok) return;
        const assets = await res.json();
        const tbody = document.getElementById('quick-assets-tbody');

        if (assets.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center">Nenhum ativo avaliado ainda. Enfileire na Smart Queue.</td></tr>`;
            return;
        }

        tbody.innerHTML = assets.slice(0, 6).map(a => renderAssetRow(a, false)).join('');
    } catch (e) {
        console.error(e);
    }
}

// 2. Gerenciador B3
async function loadAssets() {
    try {
        const res = await authFetch('/api/assets');
        if (!res || !res.ok) return;
        const assets = await res.json();
        const tbody = document.getElementById('assets-tbody');

        if (assets.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center">Nenhum ativo cadastrado. Clique em "+ Cadastrar Papel".</td></tr>`;
            return;
        }

        tbody.innerHTML = assets.map(a => renderAssetRow(a, true)).join('');
    } catch (e) {
        console.error(e);
    }
}

function renderAssetRow(a, fullView) {
    const statusClass = `badge-${a.status_analise || 'pendente'}`;
    const conviccaoPct = Math.round((a.conviccao || 0) * 100);
    const diasValidade = a.dias_restantes !== null ? `${a.dias_restantes} dias` : `${a.validade_dias || 7}d padrão`;

    return `
        <tr>
            <td><strong>${a.ticker}</strong></td>
            <td>${esc(a.nome || a.ticker.replace('.SA', ''))} <small class="text-muted">(${esc(a.setor || 'B3')})</small></td>
            <td>
                <span class="badge ${statusClass}">${a.status_analise || 'pendente'}</span>
                ${renderOriginBadge(a.decisao_origem)}
            </td>
            <td><strong>${conviccaoPct}%</strong></td>
            <td>
                <div style="font-size: 11px;">${diasValidade}</div>
                <div style="background: rgba(255,255,255,0.1); height: 4px; border-radius: 2px; width: 60px; margin-top: 3px;">
                    <div style="background: var(--primary); height: 100%; border-radius: 2px; width: ${Math.min(100, (a.dias_restantes || 7) * 14)}%;"></div>
                </div>
            </td>
            <td><small>${esc(a.tese_resumida || 'Aguardando primeira deliberação da IA.')}</small></td>
            <td style="white-space: nowrap;">
                <button class="btn btn-sm btn-outline" onclick="triggerAnalyze('${esc(a.ticker)}')">Analisar Agora</button>
                <button class="btn btn-sm btn-outline" onclick="openAssetSources('${esc(a.ticker)}')">Fontes</button>
            </td>
        </tr>
    `;
}

async function triggerAnalyze(ticker) {
    const res = await authFetch(`/api/assets/${ticker}/analyze`, { method: 'POST' });
    if (res && res.ok) {
        alert(`Ativo ${ticker} enfileirado com Alta Prioridade!`);
        loadQueueStatusLive();
    }
}

// 3. Key Pool & Orçamento
async function loadKeys() {
    try {
        const res = await authFetch('/api/keys');
        if (!res || !res.ok) return;
        const keys = await res.json();
        document.getElementById('stat-keys').innerText = keys.filter(k => k.is_active && !k.rate_limit_hit).length;

        const tbody = document.getElementById('keys-tbody');
        if (keys.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center">Nenhuma chave cadastrada. Adicione chaves gratuitas do Gemini/Claude para ativar o hot-swap.</td></tr>`;
            return;
        }

        tbody.innerHTML = keys.map(k => `
            <tr>
                <td>#${k.id}</td>
                <td><span class="badge badge-neutral">${k.provider.toUpperCase()}</span></td>
                <td>${k.label || '-'}</td>
                <td><code>${k.key_masked}</code></td>
                <td>
                    ${k.rate_limit_hit 
                        ? '<span class="badge badge-danger">Rate Limit (Cooldown)</span>' 
                        : '<span class="badge badge-success">Ativa / Disponível</span>'}
                </td>
                <td>
                    <div>${k.current_usage} / ${k.daily_limit} reqs</div>
                    <div style="background: rgba(255,255,255,0.1); height: 4px; width: 80px; border-radius: 2px; margin-top: 4px;">
                        <div style="background: ${k.current_usage > k.daily_limit * 0.8 ? 'var(--danger)' : 'var(--primary)'}; height: 100%; width: ${Math.min(100, (k.current_usage / k.daily_limit) * 100)}%;"></div>
                    </div>
                </td>
                <td>Prioridade ${k.priority}</td>
                <td>
                    <button class="btn btn-sm btn-outline" onclick="deleteKey(${k.id})">Remover</button>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        console.error(e);
    }
}

async function deleteKey(id) {
    if (!confirm('Remover esta chave de API do Pool?')) return;
    const res = await authFetch(`/api/keys/${id}`, { method: 'DELETE' });
    if (res && res.ok) loadKeys();
}

// 4. Smart Queue & Webhooks
async function loadWebhooks() {
    try {
        const res = await authFetch('/api/webhooks/outbox');
        if (!res || !res.ok) return;
        const outbox = await res.json();
        const tbody = document.getElementById('webhooks-tbody');

        const pending = outbox.filter(o => o.status === 'pending').length;
        document.getElementById('outbox-pending-badge').innerText = `${pending} Pendentes na Fila`;

        if (outbox.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center">Nenhum webhook disparado ainda.</td></tr>`;
            return;
        }

        tbody.innerHTML = outbox.map(o => `
            <tr>
                <td>#${o.id}</td>
                <td><code>${o.target_url}</code></td>
                <td>
                    <span class="badge ${o.status === 'delivered' ? 'badge-success' : o.status === 'pending' ? 'badge-warning' : 'badge-danger'}">
                        ${o.status}
                    </span>
                </td>
                <td>${o.retry_count} tentativas</td>
                <td><small><code>${JSON.stringify(o.payload_json).slice(0, 70)}...</code></small></td>
                <td><small class="text-danger">${o.last_error || '-'}</small></td>
            </tr>
        `).join('');
    } catch (e) {
        console.error(e);
    }
}

async function forceRetryWebhooks() {
    const res = await authFetch('/api/webhooks/retry-all', { method: 'POST' });
    if (res && res.ok) {
        alert('Processamento de retentativas executado!');
        loadWebhooks();
    }
}

// 5. Memória Pós-Morte (Settle-and-Reflect)
async function loadMemories() {
    try {
        const res = await authFetch('/api/memory/lessons');
        if (!res || !res.ok) return;
        const memories = await res.json();
        const tbody = document.getElementById('memory-tbody');

        if (memories.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="text-center">Nenhum feedback de trade registrado ainda. Registre acima para ver a IA refletir.</td></tr>`;
            return;
        }

        tbody.innerHTML = memories.map(m => `
            <tr>
                <td><strong>${m.ticker}</strong></td>
                <td><span class="badge badge-${m.resultado.toLowerCase()}">${m.resultado}</span></td>
                <td>${m.motivo_grafico || '-'}</td>
                <td>${m.licao_aprendida}</td>
                <td><small class="text-muted">${new Date(m.created_at).toLocaleString('pt-BR')}</small></td>
            </tr>
        `).join('');
    } catch (e) {
        console.error(e);
    }
}

// 6. Watchdogs & Configurações
async function loadWatchdogs() {
    try {
        const res = await authFetch('/api/watchdog/status');
        if (!res || !res.ok) return;
        const data = await res.json();

        // Upstream
        document.getElementById('watchdog-up-local').innerText = (data.upstream.current_commit || 'init').slice(0, 10);
        document.getElementById('watchdog-up-remote').innerText = (data.upstream.remote_commit || 'sincronizado').slice(0, 10);

        const banner = document.getElementById('watchdog-banner');
        if (data.upstream.update_available) {
            banner.classList.remove('hidden');
            document.getElementById('watchdog-banner-msg').innerText = 'Nova versão oficial detectada no TauricResearch. Atualização manual disponível.';
        } else if (data.custom && data.custom.update_available) {
            banner.classList.remove('hidden');
            document.getElementById('watchdog-banner-msg').innerText = 'Atualização customizada B3 agendada com segurança para as 03:00 AM.';
        } else {
            banner.classList.add('hidden');
        }

        // Custom
        if (data.custom && data.custom.scheduled_update_at) {
            document.getElementById('watchdog-cust-sched').innerText = `Agendado: ${new Date(data.custom.scheduled_update_at).toLocaleString('pt-BR')}`;
        }
    } catch (e) {
        console.error(e);
    }
}

async function checkWatchdogs() {
    const res = await authFetch('/api/watchdog/check', { method: 'POST' });
    if (res && res.ok) {
        alert('Verificação de repositórios do Watchdog concluída!');
        loadWatchdogs();
    }
}

async function loadSettings() {
    try {
        const res = await authFetch('/api/settings');
        if (!res || !res.ok) return;
        const s = await res.json();
        if (s.technical_robot_webhook_url) document.getElementById('set-robot-url').value = s.technical_robot_webhook_url;
        if (s.evolution_api_url) document.getElementById('set-evolution-url').value = s.evolution_api_url;
        if (s.evolution_instance) document.getElementById('set-evolution-instance').value = s.evolution_instance;
        if (s.evolution_recipient_number) document.getElementById('set-evolution-number').value = s.evolution_recipient_number;
    } catch (e) {
        console.error(e);
    }
}

// 7. Logs de Auditoria
async function loadLogs() {
    try {
        const res = await authFetch('/api/logs?limit=50');
        if (!res || !res.ok) return;
        const logs = await res.json();
        const container = document.getElementById('logs-container');

        if (logs.length === 0) {
            container.innerHTML = '<div class="log-line">Nenhum log registrado.</div>';
            return;
        }

        container.innerHTML = logs.map(l => `
            <div class="log-line ${l.level}">
                [${new Date(l.created_at).toLocaleTimeString()}] [${l.level}] [${l.category}] ${l.message}
            </div>
        `).join('');
    } catch (e) {
        console.error(e);
    }
}

// Formulários
function initForms() {
    // Demanda Robô Técnico
    const demandForm = document.getElementById('demand-form');
    if (demandForm) {
        demandForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const raw = document.getElementById('demand-tickers').value;
            const prioridade = document.getElementById('demand-priority').value;
            const tickers = raw.split(',').map(t => t.trim()).filter(t => t.length > 0);

            const res = await authFetch('/api/queue/demand', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ativos: tickers, prioridade, origem: 'cockpit_simulacao' })
            });

            if (res && res.ok) {
                const data = await res.json();
                alert(`Sucesso! ${data.total_enfileirados} ativos adicionados à Fila.`);
                document.getElementById('demand-tickers').value = '';
                loadQueueStatusLive();
            }
        });
    }

    // Feedback Trade (Memória)
    const fbForm = document.getElementById('feedback-form');
    if (fbForm) {
        fbForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const ativo = document.getElementById('fb-ticker').value;
            const resultado = document.getElementById('fb-resultado').value;
            const motivo_grafico = document.getElementById('fb-motivo').value;

            const res = await authFetch('/api/memory/feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ativo, resultado, motivo_grafico })
            });

            if (res && res.ok) {
                alert('Reflexão pós-morte concluída e lição aprendida gravada!');
                document.getElementById('fb-ticker').value = '';
                document.getElementById('fb-motivo').value = '';
                loadMemories();
            }
        });
    }

    // Modal Add Ativo
    const addAssetForm = document.getElementById('add-asset-form');
    if (addAssetForm) {
        addAssetForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const ticker = document.getElementById('new-asset-ticker').value;
            const nome = document.getElementById('new-asset-name').value;
            const setor = document.getElementById('new-asset-sector').value;

            const res = await authFetch('/api/assets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ticker, nome, setor })
            });

            if (res && res.ok) {
                closeModals();
                loadAssets();
            }
        });
    }

    // Modal Add Key
    const addKeyForm = document.getElementById('add-key-form');
    if (addKeyForm) {
        addKeyForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const provider = document.getElementById('new-key-provider').value;
            const label = document.getElementById('new-key-label').value;
            const key_value = document.getElementById('new-key-value').value;
            const daily_limit = parseInt(document.getElementById('new-key-limit').value) || 1000;
            const priority = parseInt(document.getElementById('new-key-priority').value) || 1;

            const res = await authFetch('/api/keys', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider, label, key_value, daily_limit, priority })
            });

            if (res && res.ok) {
                closeModals();
                loadKeys();
            }
        });
    }

    // Fontes de Dados: testar todas
    const sourceTestForm = document.getElementById('source-test-form');
    if (sourceTestForm) {
        sourceTestForm.addEventListener('submit', (e) => {
            e.preventDefault();
            testAllSources();
        });
    }

    // Fontes de Dados: cadastrar RSS
    const addSourceForm = document.getElementById('add-source-form');
    if (addSourceForm) {
        addSourceForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const nome = document.getElementById('new-source-name').value;
            const url_template = document.getElementById('new-source-url').value;
            const res = await authFetch('/api/sources', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nome, url_template })
            });
            if (res && res.ok) {
                const data = await res.json();
                closeModals();
                addSourceForm.reset();
                await loadSources();
                testSource(data.source_id);
            } else if (res) {
                const err = await res.json().catch(() => ({}));
                alert(`Não foi possível cadastrar: ${typeof err.detail === 'string' ? err.detail : 'dados inválidos'}`);
            }
        });
    }

    // Atualização: salvar canal
    const channelForm = document.getElementById('update-channel-form');
    if (channelForm) {
        channelForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const value = document.getElementById('update-channel').value.trim();
            const res = await authFetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: 'update_channel', value })
            });
            if (res && res.ok) {
                setUpdateBanner('✓ Canal salvo. Clique em Verificar.', 'ok');
            }
        });
    }

    // Atualização: envio manual do .zip
    const uploadForm = document.getElementById('update-upload-form');
    if (uploadForm) {
        uploadForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const file = document.getElementById('update-file').files[0];
            if (!file) { alert('Escolha o arquivo TradingAgentsB3-app-X.Y.Z.zip'); return; }
            if (!confirm(`Atualizar usando o arquivo ${file.name}?\n\nO sistema fica fora do ar por cerca de 1 minuto.`)) return;
            const fd = new FormData();
            fd.append('file', file);
            startUpdate(() => authFetch('/api/update/upload', { method: 'POST', body: fd }));
        });
    }

    // Token brapi.dev
    const brapiForm = document.getElementById('brapi-token-form');
    if (brapiForm) {
        brapiForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const value = document.getElementById('brapi-token').value.trim();
            const res = await authFetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: 'brapi_token', value })
            });
            if (res && res.ok) {
                document.getElementById('brapi-token').value = '';
                document.getElementById('brapi-token-status').innerText = value ? '✓ Token salvo.' : 'Token removido.';
            }
        });
    }

    // Salvar Configurações
    const settingsForm = document.getElementById('settings-form');
    if (settingsForm) {
        settingsForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const robotUrl = document.getElementById('set-robot-url').value;
            const evoUrl = document.getElementById('set-evolution-url').value;
            const evoKey = document.getElementById('set-evolution-key').value;
            const evoInst = document.getElementById('set-evolution-instance').value;
            const evoNum = document.getElementById('set-evolution-number').value;

            if (robotUrl) await authFetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: 'technical_robot_webhook_url', value: robotUrl }) });
            if (evoUrl) await authFetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: 'evolution_api_url', value: evoUrl }) });
            if (evoKey) await authFetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: 'evolution_api_key', value: evoKey }) });
            if (evoInst) await authFetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: 'evolution_instance', value: evoInst }) });
            if (evoNum) await authFetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: 'evolution_recipient_number', value: evoNum }) });

            alert('Configurações atualizadas com sucesso!');
        });
    }
}

// ==========================================
// Utilitários de segurança/formatação
// (conteúdo de fontes externas e da IA nunca entra no HTML sem escape)
// ==========================================
function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function safeUrl(u) {
    return /^https?:\/\//i.test(u || '') ? esc(u) : '#';
}

function fmtDateTime(iso) {
    if (!iso) return '-';
    // API devolve UTC sem "Z"
    const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z');
    return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
}

function fmtAgo(iso) {
    if (!iso) return 'nunca';
    const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z');
    const min = Math.round((Date.now() - d.getTime()) / 60000);
    if (min < 1) return 'agora';
    if (min < 60) return `há ${min} min`;
    if (min < 1440) return `há ${Math.round(min / 60)} h`;
    return `há ${Math.round(min / 1440)} d`;
}

function fmtNum(v) {
    if (v === null || v === undefined || v === '') return '-';
    if (typeof v !== 'number') return esc(v);
    return v.toLocaleString('pt-BR', { maximumFractionDigits: 2 });
}

function renderOriginBadge(origem) {
    if (!origem) return '';
    const isIA = origem.startsWith('IA:');
    const cls = isIA ? 'badge-info' : 'badge-warning';
    const label = isIA ? `🤖 ${origem.replace('IA: ', '')}` : `⚠ ${origem}`;
    return `<div><span class="badge badge-origin ${cls}" title="Quem tomou a decisão">${esc(label)}</span></div>`;
}

// ==========================================
// Fontes de Dados
// ==========================================
const CATEGORIA_LABEL = {
    fundamentos: 'Fundamentos', cotacao: 'Cotação', noticias: 'Notícias',
    regulatorio: 'Regulatório (CVM)', macro: 'Macroeconomia'
};
const CATEGORIA_BADGE = {
    fundamentos: 'badge-info', cotacao: 'badge-info', noticias: 'badge-neutral',
    regulatorio: 'badge-success', macro: 'badge-warning'
};

async function loadSources() {
    try {
        const res = await authFetch('/api/sources');
        if (!res || !res.ok) return;
        const fontes = await res.json();
        const tbody = document.getElementById('sources-tbody');
        tbody.innerHTML = fontes.map(f => {
            const status = f.last_status === 'ok'
                ? '<span class="badge badge-success">OK</span>'
                : f.last_status === 'erro'
                    ? '<span class="badge badge-danger">Falha</span>'
                    : '<span class="badge badge-neutral">Não testada</span>';
            const ultimo = f.last_status === 'erro'
                ? `<div class="source-last erro">${esc(f.last_error)}</div>`
                : `<div class="source-last">${esc(f.last_resumo || '-')}</div>`;
            const sid = esc(f.id);
            return `
            <tr>
                <td>
                    <label class="switch" title="${f.enabled ? 'Ligada: usada nas análises' : 'Desligada'}">
                        <input type="checkbox" ${f.enabled ? 'checked' : ''} onchange="toggleSource('${sid}', this.checked)">
                        <span class="slider"></span>
                    </label>
                </td>
                <td>
                    <div class="source-name">${esc(f.nome)}${f.site ? `<a href="${safeUrl(f.site)}" target="_blank" rel="noopener">site ↗</a>` : ''}</div>
                    <div class="source-desc">${esc(f.descricao)}</div>
                    ${f.url_template && f.removivel ? `<div class="source-desc"><code>${esc(f.url_template)}</code></div>` : ''}
                </td>
                <td><span class="badge ${CATEGORIA_BADGE[f.categoria] || 'badge-neutral'}">${esc(f.categoria_label)}</span></td>
                <td>
                    ${status}
                    <div class="text-muted" style="font-size: 11px; margin-top: 3px;">${fmtAgo(f.last_checked_at)} · ${f.ok_count}✓ ${f.fail_count}✗</div>
                </td>
                <td>${f.last_latency_ms != null ? `${f.last_latency_ms} ms` : '-'}</td>
                <td>${ultimo}</td>
                <td style="white-space: nowrap;">
                    <button class="btn btn-sm btn-outline" onclick="testSource('${sid}', this)">Testar</button>
                    ${f.removivel ? `<button class="btn btn-sm btn-outline" onclick="deleteSource('${sid}')">Remover</button>` : ''}
                </td>
            </tr>`;
        }).join('');
    } catch (e) {
        console.error(e);
    }
}

function getTestTicker() {
    return (document.getElementById('source-test-ticker').value || 'PETR4').trim().toUpperCase();
}

async function toggleSource(id, enabled) {
    await authFetch(`/api/sources/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled })
    });
    loadSources();
}

async function testSource(id, btn) {
    const ticker = getTestTicker();
    const box = document.getElementById('source-test-result');
    if (btn) { btn.disabled = true; btn.innerText = 'Testando...'; }
    box.classList.remove('hidden');
    box.innerHTML = `<div class="text-muted">Testando ${esc(id)} com ${esc(ticker)}...</div>`;
    try {
        const res = await authFetch(`/api/sources/${encodeURIComponent(id)}/test?ticker=${encodeURIComponent(ticker)}`, { method: 'POST' });
        if (!res || !res.ok) {
            box.innerHTML = '<div class="source-last erro">Falha ao executar o teste.</div>';
            return;
        }
        const r = await res.json();
        box.innerHTML = `<h4 style="font-size: 13px; margin-bottom: 8px;">Resultado do teste com ${esc(ticker)}</h4>
            <div class="source-grid">${renderSourceCard(r, true)}</div>`;
    } finally {
        if (btn) { btn.disabled = false; btn.innerText = 'Testar'; }
        loadSources();
    }
}

async function testAllSources() {
    const ticker = getTestTicker();
    const box = document.getElementById('source-test-result');
    const btn = document.getElementById('source-test-all-btn');
    btn.disabled = true; btn.innerText = 'Testando...';
    box.classList.remove('hidden');
    box.innerHTML = `<div class="text-muted">Consultando todas as fontes para ${esc(ticker)}... (a 1ª consulta da CVM baixa arquivos e pode levar alguns segundos)</div>`;
    try {
        const res = await authFetch(`/api/sources/test-all?ticker=${encodeURIComponent(ticker)}`, { method: 'POST' });
        if (!res || !res.ok) {
            box.innerHTML = '<div class="source-last erro">Falha ao executar o teste.</div>';
            return;
        }
        const data = await res.json();
        box.innerHTML = renderConsolidado(data.consolidado, data.ticker) +
            `<div class="source-grid">${data.resultados.map(r => renderSourceCard(r, true)).join('')}</div>`;
    } finally {
        btn.disabled = false; btn.innerText = 'Testar todas';
        loadSources();
    }
}

// Nome amigável e ordem de exibição dos indicadores
const IND_LABELS = {
    PL: 'P/L', PVP: 'P/VP', DY_pct: 'DY', ROE_pct: 'ROE', ROIC_pct: 'ROIC', EV_EBITDA: 'EV/EBITDA',
    Margem_Liquida_pct: 'Marg. Líquida', Margem_Ebitda_pct: 'Marg. EBITDA', Margem_EBIT_pct: 'Marg. EBIT',
    Margem_Bruta_pct: 'Marg. Bruta', Div_Liq_Patrimonio: 'Dív.Líq/PL', Liquidez_Corrente: 'Liq. Corrente',
    Cresc_Receita_5a_pct: 'Cresc. Receita 5a', LPA: 'LPA', VPA: 'VPA',
    Valor_Mercado: 'Valor de Mercado', Volume_Medio_2m: 'Volume médio 2m'
};
const IND_ORDER = Object.keys(IND_LABELS);

function fmtIndicador(k, v) {
    if (typeof v !== 'number') return esc(v);
    if (k.endsWith('_pct')) return `${fmtNum(v)}%`;
    if (Math.abs(v) >= 1e9) return `R$ ${(v / 1e9).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} bi`;
    if (Math.abs(v) >= 1e6) return `R$ ${(v / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} mi`;
    return fmtNum(v);
}

function renderIndicadores(ind, fontesInd) {
    const keys = Object.keys(ind || {}).sort((a, b) =>
        (IND_ORDER.indexOf(a) + 1 || 99) - (IND_ORDER.indexOf(b) + 1 || 99));
    if (!keys.length) return '<span class="text-muted">Nenhum indicador.</span>';
    return `<div class="ind-chips">${keys.map(k =>
        `<span class="ind-chip" title="${esc(k)}">${esc(IND_LABELS[k] || k)}: ${fmtIndicador(k, ind[k])}${fontesInd && fontesInd[k] ? ` <small>(${esc(fontesInd[k])})</small>` : ''}</span>`
    ).join('')}</div>`;
}

function renderAvisos(avisos) {
    if (!avisos || !avisos.length) return '';
    return `<ul class="aviso-list">${avisos.map(a => `<li>⚠ ${esc(a)}</li>`).join('')}</ul>`;
}

function renderConsolidado(c, ticker) {
    const statusLabel = { sucesso_primario: 'Dados completos', sucesso_fallback: 'Só notícias/CVM', pausa_analise: 'Trava de segurança' };
    return `
        <div class="consolidado-box">
            <h4>O que a IA receberia para ${esc(ticker)} (somente fontes ligadas)</h4>
            <div><strong>${esc(statusLabel[c.status_coleta] || c.status_coleta)}</strong> ·
                Preço R$ ${fmtNum(c.preco_atual)} · ${c.qtd_noticias} notícias ·
                Fontes que responderam: ${esc(c.fonte_utilizada)}</div>
            ${renderIndicadores(c.indicadores, c.indicadores_fontes)}
            ${renderAvisos(c.avisos)}
        </div>`;
}

function renderSourceCard(r, showRaw) {
    const head = `
        <div class="source-card-head">
            <strong>${esc(r.fonte_nome)}</strong>
            ${r.ok ? '<span class="badge badge-success">OK</span>' : '<span class="badge badge-danger">Falha</span>'}
        </div>
        <div class="meta">${esc(CATEGORIA_LABEL[r.categoria] || r.categoria)} · ${r.latencia_ms} ms</div>`;
    const resumo = r.ok ? `<div class="resumo">${esc(r.resumo)}</div>` : `<div class="erro">${esc(r.erro)}</div>`;
    const avisos = (r.avisos || []).map(a => `<div class="aviso">⚠ ${esc(a)}</div>`).join('');
    const itens = (r.itens || []).length
        ? `<ul>${r.itens.slice(0, 6).map(i =>
            `<li>${i.data ? `<span class="meta">${esc(i.data)}</span> ` : ''}<a href="${safeUrl(i.link)}" target="_blank" rel="noopener">${esc(i.titulo)}</a>${i.fonte && i.fonte !== r.fonte_nome ? ` <span class="meta">· ${esc(i.fonte)}</span>` : ''}</li>`
        ).join('')}</ul>`
        : '';
    const ind = r.dados && r.dados.indicadores && Object.keys(r.dados.indicadores).length
        ? renderIndicadores(r.dados.indicadores) : '';
    const raw = showRaw && r.ok
        ? `<details><summary>Ver dados brutos</summary><pre>${esc(JSON.stringify(r.dados, null, 2))}</pre></details>` : '';
    return `<div class="source-card ${r.ok ? '' : 'falha'}">${head}${resumo}${avisos}${ind}${itens}${raw}</div>`;
}

async function deleteSource(id) {
    if (!confirm('Remover esta fonte RSS?')) return;
    const res = await authFetch(`/api/sources/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (res && res.ok) loadSources();
}

function showAddSourceModal() {
    document.getElementById('modal-source').classList.remove('hidden');
}

async function loadBrapiTokenStatus() {
    try {
        const res = await authFetch('/api/settings');
        if (!res || !res.ok) return;
        const s = await res.json();
        const el = document.getElementById('brapi-token-status');
        if (s.brapi_token) el.innerText = '✓ Token configurado. Cole outro para substituir.';
    } catch (e) {
        console.error(e);
    }
}

// Resumo de fontes de um ativo (últimas análises)
let assetRunsCache = [];

async function openAssetSources(ticker) {
    const modal = document.getElementById('modal-asset-sources');
    const body = document.getElementById('asset-sources-body');
    document.getElementById('asset-sources-title').innerText = `Fontes consultadas · ${ticker.replace('.SA', '')}`;
    body.innerHTML = '<div class="text-muted">Carregando...</div>';
    modal.classList.remove('hidden');

    const res = await authFetch(`/api/assets/${encodeURIComponent(ticker)}/sources`);
    if (!res || !res.ok) {
        body.innerHTML = '<div class="source-last erro">Falha ao carregar.</div>';
        return;
    }
    assetRunsCache = await res.json();
    if (!assetRunsCache.length) {
        body.innerHTML = `<div class="text-muted">Este ativo ainda não foi analisado com o novo registro de fontes.
            Clique em "Analisar Agora" e abra esta janela de novo quando a fila terminar.</div>`;
        return;
    }
    renderAssetRun(0);
}

function renderAssetRun(idx) {
    const run = assetRunsCache[idx];
    const body = document.getElementById('asset-sources-body');
    const tabs = assetRunsCache.length > 1
        ? `<div class="run-tabs">${assetRunsCache.map((r, i) =>
            `<button class="btn btn-sm btn-outline ${i === idx ? 'active' : ''}" onclick="renderAssetRun(${i})">${fmtDateTime(r.created_at)}</button>`
        ).join('')}</div>` : '';
    const ok = run.fontes.filter(f => f.ok).length;
    const v = run.veredito || {};
    body.innerHTML = `
        ${tabs}
        <div class="run-section">
            <h4>Decisão de ${fmtDateTime(run.created_at)}</h4>
            <div>
                ${v.status ? `<span class="badge badge-${esc(v.status)}">${esc(v.status)}</span>` : ''}
                ${v.conviccao != null ? `<strong style="margin: 0 8px;">${Math.round(v.conviccao * 100)}% convicção</strong>` : ''}
                ${renderOriginBadge(run.decisao_origem)}
            </div>
            ${run.erro_llm ? `<div class="source-last erro" style="margin-top: 6px;">Por que não usou IA: ${esc(run.erro_llm)}</div>` : ''}
            ${v.tese_resumida ? `<p style="margin-top: 8px; font-size: 13px;">${esc(v.tese_resumida)}</p>` : ''}
            ${renderAvisos(run.avisos)}
        </div>
        ${run.triagem_texto ? `
        <div class="run-section">
            <h4>Triagem de notícias <span class="text-muted">(${esc(run.triagem_origem || '-')})</span></h4>
            <div class="triagem-box">${esc(run.triagem_texto.replace(/\*\*/g, ''))}</div>
        </div>` : ''}
        <div class="run-section">
            <h4>Fontes (${ok} de ${run.fontes.length} responderam)</h4>
            <div class="source-grid">${run.fontes.map(f => renderSourceCard(f, false)).join('')}</div>
        </div>`;
}

// ==========================================
// Atualização do Sistema
// ==========================================
function setUpdateBanner(html, tipo) {
    const b = document.getElementById('update-banner');
    if (!html) { b.classList.add('hidden'); return; }
    b.className = `update-banner ${tipo || ''}`;
    b.innerHTML = html;
}

async function loadUpdateStatus() {
    try {
        const res = await authFetch('/api/update/status');
        if (!res || !res.ok) return;
        const s = await res.json();
        document.getElementById('update-installed').innerText = s.versao_instalada;
        document.getElementById('update-channel').value = s.canal || '';
        const r = s.ultimo_resultado;
        if (r) {
            setUpdateBanner(`${r.ok ? '✓' : '⚠'} ${esc(r.mensagem)} <span class="text-muted">(${esc(r.quando)})</span>`, r.ok ? 'ok' : 'erro');
        } else if (!s.modo_instalado) {
            setUpdateBanner('Modo de desenvolvimento: a atualização automática funciona na versão instalada pelo instalador.', 'aviso');
        } else {
            setUpdateBanner('');
        }
    } catch (e) {
        console.error(e);
    }
}

async function checkUpdate() {
    const btn = document.getElementById('update-check-btn');
    const applyBtn = document.getElementById('update-apply-btn');
    btn.disabled = true; btn.innerText = 'Verificando...';
    try {
        const res = await authFetch('/api/update/check', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            document.getElementById('update-available').innerText = '—';
            setUpdateBanner(`⚠ ${esc(data.detail || 'Falha ao verificar.')}`, 'erro');
            applyBtn.disabled = true;
            return;
        }
        document.getElementById('update-available').innerText = data.versao_disponivel;
        document.getElementById('update-notes').innerText = data.notas || '';
        if (data.tem_atualizacao) {
            setUpdateBanner(`Nova versão <strong>${esc(data.versao_disponivel)}</strong> disponível.` +
                (data.modo_instalado ? ' Clique em <strong>Atualizar</strong>.' : ' (modo de desenvolvimento: use o instalador)'),
                data.modo_instalado ? '' : 'aviso');
            applyBtn.disabled = !data.modo_instalado;
        } else {
            setUpdateBanner('✓ O sistema já está na versão mais recente.', 'ok');
            applyBtn.disabled = true;
        }
    } catch (e) {
        setUpdateBanner('⚠ Falha ao verificar atualização.', 'erro');
    } finally {
        btn.disabled = false; btn.innerText = 'Verificar';
    }
}

function showUpdateOverlay(msg) {
    let o = document.getElementById('update-overlay');
    if (!o) {
        o = document.createElement('div');
        o.id = 'update-overlay';
        o.className = 'update-overlay';
        document.body.appendChild(o);
    }
    o.innerHTML = `<div class="spinner"></div><div>${esc(msg)}</div>
        <div class="text-muted">Não feche esta página. O banco de dados foi copiado para backup antes da troca.</div>`;
}

async function waitForRestart(versaoAntiga, versaoNova) {
    // O servidor cai e volta; /api/health é público e informa a versão em execução
    const inicio = Date.now();
    let caiu = false;
    while (Date.now() - inicio < 5 * 60 * 1000) {
        await new Promise(r => setTimeout(r, 3000));
        try {
            const r = await fetch('/api/health', { cache: 'no-store' });
            if (!r.ok) { caiu = true; continue; }
            const h = await r.json();
            if (h.version === versaoNova) {
                showUpdateOverlay(`Atualizado para ${versaoNova}! Recarregando...`);
                setTimeout(() => location.reload(), 1500);
                return;
            }
            if (caiu && h.version === versaoAntiga) {
                // voltou na versão antiga = rollback automático
                document.getElementById('update-overlay')?.remove();
                switchTab('settings');
                loadUpdateStatus();
                return;
            }
        } catch (e) {
            caiu = true;
            showUpdateOverlay(`Instalando a versão ${versaoNova}... o sistema está reiniciando.`);
        }
    }
    showUpdateOverlay('A atualização está demorando. Recarregue a página em alguns instantes.');
}

async function startUpdate(requestFn) {
    const versaoAntiga = document.getElementById('update-installed').innerText.trim();
    showUpdateOverlay('Baixando e conferindo o pacote de atualização...');
    const res = await requestFn();
    const data = res ? await res.json().catch(() => ({})) : {};
    if (!res || !res.ok) {
        document.getElementById('update-overlay')?.remove();
        setUpdateBanner(`⚠ ${esc(data.detail || 'Falha ao iniciar a atualização.')}`, 'erro');
        return;
    }
    showUpdateOverlay(`Instalando a versão ${data.versao_nova}... o sistema vai reiniciar.`);
    waitForRestart(versaoAntiga, data.versao_nova);
}

function applyUpdate() {
    const nova = document.getElementById('update-available').innerText.trim();
    if (!confirm(`Atualizar para a versão ${nova}?\n\nO sistema fica fora do ar por cerca de 1 minuto. ` +
        `Análises em andamento serão retomadas depois. Se algo der errado, a versão atual volta sozinha.`)) return;
    startUpdate(() => authFetch('/api/update/apply', { method: 'POST' }));
}

// Modais
function showAddAssetModal() {
    document.getElementById('modal-asset').classList.remove('hidden');
}

function showAddKeyModal() {
    document.getElementById('modal-key').classList.remove('hidden');
}

function closeModals() {
    document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.add('hidden'));
}

// Logout
function logout() {
    localStorage.removeItem('tradingagents_token');
    window.location.href = '/login';
}
