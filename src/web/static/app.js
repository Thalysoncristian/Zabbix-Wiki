/* Zabbix-Wiki — interface de consulta.
 *
 * Sem framework e sem build: o backend serve estes três arquivos e pronto.
 * Para ~19.000 alertas isso funciona porque a tabela NUNCA recebe a lista
 * inteira — filtro, ordenação e paginação acontecem no servidor, e cada página
 * traz no máximo algumas dezenas de linhas.
 *
 * Os filtros vivem na query string da própria URL. É de propósito: no NOC uma
 * consulta útil é colada no chamado, e ela precisa abrir igual do outro lado.
 */

const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
};

const num = (n) => (n ?? 0).toLocaleString('pt-BR');
const sevClass = (name) => 'sev-' + String(name || '').toLowerCase().replace(/[^a-z]/g, '');
const fillClass = (name) => 'fill-' + String(name || '').toLowerCase().replace(/[^a-z]/g, '');

/** Estado ausente é estado válido, não erro: nunca mostrar "erro" por falta de dado. */
const na = (texto = 'não disponível') => el('span', { class: 'na' }, texto);

/** Escopo operacional ativo, lido da URL. Vazio = o padrão do servidor. */
const escopoAtual = () => new URLSearchParams(location.search).get('scope') || '';

async function api(path, params = {}) {
  const url = new URL(path, location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v !== '' && v !== null && v !== undefined) url.searchParams.set(k, v);
  }
  // Toda leitura carrega o escopo: um endpoint sem ele responderia com o
  // escopo padrão, e a tela mostraria números de um recorte diferente do que
  // o seletor está exibindo.
  if (escopoAtual() && !url.searchParams.has('scope')) url.searchParams.set('scope', escopoAtual());
  const resposta = await fetch(url, { headers: { Accept: 'application/json' } });
  const dados = await resposta.json().catch(() => ({ error: 'Resposta inválida do servidor.' }));
  if (!resposta.ok) throw Object.assign(new Error(dados.error || `HTTP ${resposta.status}`), { payload: dados });
  return dados;
}

const view = document.getElementById('view');
const setView = (...nodes) => { view.replaceChildren(...nodes.flat().filter(Boolean)); };
const erro = (mensagem, dica) => setView(
  el('div', { class: 'note warn' },
    el('strong', {}, 'Não foi possível carregar. '), mensagem,
    dica ? el('div', { class: 'muted' }, dica) : null),
);

/* ------------------------------------------------------------------ router */
const rotas = [];
const rota = (padrao, handler) => rotas.push({ padrao, handler });

function navegar(href, substituir = false) {
  const url = new URL(href, location.origin);
  // O escopo acompanha a navegação. Injetar aqui cobre TODOS os links da
  // interface de uma vez — bem mais seguro do que lembrar de anexar `?scope=`
  // em cada href espalhado pelas telas.
  const escopo = escopoAtual();
  if (escopo && !url.searchParams.has('scope')) url.searchParams.set('scope', escopo);
  if (substituir) history.replaceState({}, '', url);
  else history.pushState({}, '', url);
  render();
}

document.addEventListener('click', (evento) => {
  const link = evento.target.closest('a');
  if (!link || link.target === '_blank' || evento.metaKey || evento.ctrlKey) return;
  const href = link.getAttribute('href') || '';
  if (!href.startsWith('/')) return;
  evento.preventDefault();
  esconderBusca();
  navegar(href);
});
addEventListener('popstate', render);

function marcarNav() {
  const caminho = location.pathname;
  for (const link of document.querySelectorAll('#nav a')) {
    const alvo = link.dataset.nav;
    link.classList.toggle('active', alvo === '/' ? caminho === '/' : caminho.startsWith(alvo));
  }
}

async function render() {
  marcarNav();
  if (!escoposDisponiveis.length) await carregarEscopos();
  else seletorEscopo.value = escopoAtual() ||
    (escoposDisponiveis.find((e) => e.is_default) || {}).id || 'all';
  const caminho = location.pathname;
  const params = Object.fromEntries(new URLSearchParams(location.search));
  setView(el('div', { class: 'loading' }, 'Carregando…'));
  for (const { padrao, handler } of rotas) {
    const match = caminho.match(padrao);
    if (match) {
      try {
        await handler(match.slice(1).map(decodeURIComponent), params);
      } catch (e) {
        erro(e.message, e.payload && e.payload.hint);
      }
      return;
    }
  }
  setView(el('div', { class: 'empty' }, 'Página não encontrada: ', caminho));
}

/* ------------------------------------------------------ blocos reutilizáveis */
function cabecalho(titulo, subtitulo, migalhas) {
  return el('div', { class: 'page-head' },
    migalhas ? el('div', { class: 'crumbs' }, migalhas) : null,
    el('h1', {}, titulo),
    subtitulo ? el('div', { class: 'subtitle' }, subtitulo) : null);
}

function badgeProcedimento(procedimento) {
  const status = typeof procedimento === 'string' ? procedimento : (procedimento?.status || 'missing');
  const rotulos = {
    missing: 'Sem procedimento', draft: 'Rascunho', documented: 'Validado',
    needs_review: 'Precisa revisão', not_applicable: 'Não aplicável',
  };
  return el('span', { class: `badge ${status}` }, rotulos[status] || status);
}

function barrasSeveridade(severidades, total) {
  const soma = total || Object.values(severidades).reduce((a, b) => a + b, 0) || 1;
  return el('div', { class: 'bars' },
    Object.entries(severidades).map(([nome, valor]) => el('div', { class: 'bar-row' },
      el('a', { class: `sev ${sevClass(nome)}`, href: `/alerts?severity=${encodeURIComponent(nome)}` }, nome),
      el('div', { class: 'bar-track' },
        el('div', { class: `bar-fill ${fillClass(nome)}`, style: `width:${(valor / soma) * 100}%` })),
      el('div', { class: 'bar-value' }, num(valor)))));
}

function severidadesInline(severidades) {
  const entradas = Object.entries(severidades || {});
  if (!entradas.length) return na('—');
  return el('span', {}, entradas.map(([nome, valor], i) => el('span', {},
    i ? '  ' : '', el('span', { class: `sev ${sevClass(nome)}` }, `${nome} ${num(valor)}`))));
}

function tabela(colunas, linhas) {
  return el('div', { class: 'table-wrap' },
    el('table', {},
      el('thead', {}, el('tr', {}, colunas.map((c) => el('th', { class: c.num ? 'num' : null }, c.label)))),
      el('tbody', {}, linhas.length
        ? linhas
        : el('tr', {}, el('td', { colspan: colunas.length }, el('div', { class: 'empty' }, 'Nada encontrado com esses filtros.'))))));
}

function paginador(paginacao, aoTrocar) {
  if (!paginacao || paginacao.pages <= 1) {
    return el('div', { class: 'pager muted' }, `${num(paginacao?.total ?? 0)} resultado(s)`);
  }
  return el('div', { class: 'pager' },
    el('button', { disabled: !paginacao.has_prev, onclick: () => aoTrocar(paginacao.page - 1) }, '‹ Anterior'),
    el('span', { class: 'muted' },
      `Página ${num(paginacao.page)} de ${num(paginacao.pages)} · ${num(paginacao.total)} resultado(s)`),
    el('button', { disabled: !paginacao.has_next, onclick: () => aoTrocar(paginacao.page + 1) }, 'Próxima ›'));
}

/** Reescreve a query string da página atual, preservando o que não mudou. */
function comFiltros(mudancas) {
  const params = new URLSearchParams(location.search);
  for (const [k, v] of Object.entries(mudancas)) {
    if (v === '' || v === null || v === undefined) params.delete(k);
    else params.set(k, v);
  }
  if (!('page' in mudancas)) params.delete('page');
  const escopo = escopoAtual();
  if (escopo) params.set('scope', escopo);
  const query = params.toString();
  return location.pathname + (query ? `?${query}` : '');
}

const aplicarFiltro = (mudancas) => navegar(comFiltros(mudancas));

function campoBusca(params, placeholder) {
  const input = el('input', { type: 'search', placeholder, value: params.q || '' });
  const form = el('form', { class: 'filters', onsubmit: (e) => { e.preventDefault(); aplicarFiltro({ q: input.value }); } },
    input, el('button', { type: 'submit' }, 'Buscar'),
    params.q ? el('button', { type: 'button', onclick: () => aplicarFiltro({ q: '' }) }, 'Limpar') : null);
  return { form, input };
}

function seletor(rotulo, nome, opcoes, params) {
  const select = el('select', { onchange: (e) => aplicarFiltro({ [nome]: e.target.value }) },
    el('option', { value: '' }, rotulo),
    opcoes.map(([valor, texto]) => el('option', { value: valor, selected: params[nome] === valor }, texto)));
  return select;
}

/* ------------------------------------------------------ escopo operacional */
const seletorEscopo = document.getElementById('scope-select');
const notaEscopo = document.getElementById('scope-note');
let escoposDisponiveis = [];

async function carregarEscopos() {
  try {
    const dados = await api('/api/scopes');
    escoposDisponiveis = dados.scopes || [];
  } catch { escoposDisponiveis = []; }

  const ativo = escopoAtual() || (escoposDisponiveis.find((e) => e.is_default) || {}).id || 'all';
  seletorEscopo.replaceChildren(...escoposDisponiveis.map((e) =>
    el('option', { value: e.id, selected: e.id === ativo }, e.label)));
  // Um escopo só (nenhum scopes.json configurado): o seletor não decide nada.
  seletorEscopo.parentElement.hidden = escoposDisponiveis.length < 2;
  descreverEscopo(ativo);
}

function descreverEscopo(id) {
  const escopo = escoposDisponiveis.find((e) => e.id === id);
  if (!escopo || escopo.is_everything) {
    notaEscopo.textContent = 'Mostrando tudo que foi coletado.';
    return;
  }
  const quantos = (escopo.exclude_hosts || []).length + (escopo.exclude_host_patterns || []).length;
  notaEscopo.textContent = escopo.mode === 'include'
    ? `Somente os hosts listados no escopo ${escopo.label}.`
    : `${quantos} host(s) fora do escopo ${escopo.label}.`;
}

seletorEscopo.addEventListener('change', () => {
  const params = new URLSearchParams(location.search);
  params.set('scope', seletorEscopo.value);
  // Trocar de escopo volta para a primeira página: os totais mudaram, e a
  // página 40 do escopo anterior provavelmente nem existe no novo.
  params.delete('page');
  descreverEscopo(seletorEscopo.value);
  navegar(`${location.pathname}?${params.toString()}`);
});

/** Faixa das duas visões: o que o escopo mostra e o que ele deixou de fora. */
function faixaEscopo(escopo, ambiente) {
  if (!escopo || escopo.is_everything) {
    return el('div', { class: 'scope-banner' },
      el('span', {}, 'Escopo: ', el('strong', {}, escopo?.label || 'Ambiente inteiro')),
      el('span', { class: 'out' }, 'mostrando todo o ambiente coletado'));
  }
  const fora = escopo.alerts_out_of_scope || 0;
  const total = ambiente?.alerts || (escopo.alerts_in_scope + fora);
  const pct = total ? Math.round((fora / total) * 100) : 0;
  return el('div', { class: 'scope-banner' },
    el('span', {}, 'Escopo: ', el('strong', {}, escopo.label)),
    el('span', {}, el('strong', {}, num(escopo.alerts_in_scope)), ' alertas nesta visão'),
    el('span', { class: 'out' },
      `${num(fora)} de ${num(total)} alertas fora do escopo (${pct}%)`),
    el('a', { href: comFiltrosEscopo('all') }, 'ver ambiente inteiro →'));
}

/** URL atual trocando apenas o escopo. */
function comFiltrosEscopo(id) {
  const params = new URLSearchParams(location.search);
  params.set('scope', id);
  params.delete('page');
  return `${location.pathname}?${params.toString()}`;
}

/* -------------------------------------------------------------- dashboard */
rota(/^\/$/, async () => {
  const dados = await api('/api/dashboard');
  atualizarBadgeSnapshot(dados.snapshot);

  const w = dados.work;
  setView(
    cabecalho('Documentação NOC', escopoTexto(dados.snapshot)),
    faixaEscopo(dados.scope, dados.environment),
    dados.snapshot.partial ? el('div', { class: 'note warn' },
      'Este snapshot é PARCIAL: objetos ficaram de fora da coleta. Os números abaixo não representam o escopo inteiro.') : null,

    // O trabalho vem primeiro. Os números técnicos continuam disponíveis,
    // mas não dominam mais a tela.
    el('section', { class: 'panel' },
      el('h2', {}, 'O que precisa ser documentado'),
      el('div', { class: 'progress-line', style: 'margin:10px 0 14px' },
        barraProgresso(w.progress),
        el('span', {}, el('strong', {}, `${num(w.documented)} de ${num(w.rules_active)}`),
          ` regras documentadas (${w.progress}%)`)),
      el('div', { class: 'chips' },
        el('span', { class: 'chip' }, `${num(w.pending)} pendentes`),
        el('span', { class: 'chip' }, `${num(w.in_progress)} em andamento`),
        el('span', { class: 'chip' }, `${num(w.documented)} documentadas`),
        el('span', { class: 'chip' }, `${num(w.confirmed)} confirmadas`)),
      el('div', { style: 'margin-top:14px' },
        el('a', { class: 'cta', href: '/groups' }, 'ESCOLHER GRUPO PARA DOCUMENTAR'))),

    w.next_rules.length ? el('section', {},
      el('h2', {}, 'Próximas regras'),
      el('div', { class: 'work-cards' }, w.next_rules.map(cardRegra))) : null,

    el('section', {},
      el('h2', {}, 'Progresso por grupo'),
      el('div', { class: 'work-cards' }, w.groups.map((g) => el('a', {
        class: 'work-card', href: `/groups/${g.id}`,
      },
        el('h3', {}, g.name),
        el('div', { class: 'meta' }, `${num(g.hosts)} hosts · ${num(g.alerts)} alertas`),
        linhaProgresso(g.rules))))),

    el('h2', {}, 'Números da coleta'),
    el('div', { class: 'cards' }, dados.cards.map((c) => el('a', { class: 'card', href: c.href },
      el('div', { class: 'card-value' }, num(c.value)),
      el('div', { class: 'card-label' }, c.label)))),

    el('div', { class: 'grid-2', style: 'margin-top:14px' },
      el('section', { class: 'panel' }, el('h2', {}, 'Distribuição por severidade'),
        barrasSeveridade(Object.fromEntries(dados.severities.map((s) => [s.name, s.value])))),
      el('section', { class: 'panel' }, el('h2', {}, 'Indicadores de qualidade'),
        el('div', { class: 'bars' }, dados.quality.map((q) => el('div', { class: 'bar-row' },
          el('a', { href: q.href }, q.label),
          el('div', {}), el('div', { class: 'bar-value' }, num(q.value))))))),

    el('section', { class: 'panel' },
      el('h2', {}, 'Top famílias'),
      el('div', { class: 'subtitle', style: 'margin-bottom:8px' },
        'A família é o nível em que o procedimento costuma ser único: escrever um procedimento aqui cobre todos os alertas da linha.'),
      tabela(
        [{ label: 'Família' }, { label: 'Origem' }, { label: 'Alertas', num: true },
         { label: 'Hosts', num: true }, { label: 'Grupos' }, { label: 'Procedimento' }],
        dados.top_families.map((f) => el('tr', {},
          el('td', {}, el('a', { href: `/families/${f.id}` }, f.label)),
          el('td', { class: 'cell-sub' }, f.origin),
          el('td', { class: 'num' }, num(f.alerts)),
          el('td', { class: 'num' }, num(f.hosts)),
          el('td', { class: 'cell-sub' }, f.host_groups.slice(0, 2).join(', ') || '—'),
          el('td', {}, badgeProcedimento(f.procedure)))))),
  );
});

const escopoTexto = (s) => `${s.scope_label} · coletado em ${s.collected_at || '?'} · Zabbix ${s.zabbix_version || '?'}`;

function atualizarBadgeSnapshot(snapshot) {
  const badge = document.getElementById('snapshot-badge');
  if (snapshot) badge.textContent = snapshot.name;
}

/* ----------------------------------------------------------------- alertas */
rota(/^\/alerts$/, async (_m, params) => {
  const dados = await api('/api/alerts', { ...params, per_page: params.per_page || 50 });
  const { form } = campoBusca(params, 'certificado, VPN, API, ICMP, disco…');

  form.append(
    seletor('Severidade', 'severity',
      ['Disaster', 'High', 'Average', 'Warning', 'Information', 'Not classified'].map((s) => [s, s]), params),
    seletor('Procedimento', 'procedure', [
      ['missing', 'Sem procedimento'], ['draft', 'Rascunho'], ['documented', 'Validado'],
      ['needs_review', 'Precisa revisão'], ['not_applicable', 'Não aplicável']], params),
    seletor('Origem', 'discovered', [['1', 'Somente LLD'], ['0', 'Somente não-LLD']], params),
    seletor('Comentário', 'comment', [['1', 'Com comentário'], ['0', 'Sem comentário']], params),
    seletor('Tags', 'tags', [['1', 'Com tags'], ['0', 'Sem tags']], params),
    seletor('Dependência', 'dependencies', [['1', 'Com dependência'], ['0', 'Sem dependência']], params),
    seletor('Colisão', 'collision', [['1', 'Somente colisões'], ['0', 'Sem colisão']], params),
  );

  setView(
    cabecalho('Alertas', `${num(dados.pagination.total)} de ${num(dados.facets.total_unfiltered)} alertas do snapshot`),
    form,
    tabela(
      [{ label: 'Alerta' }, { label: 'Host' }, { label: 'Severidade' }, { label: 'Família' }, { label: 'Sinais' }, { label: 'Procedimento' }],
      dados.items.map((a) => el('tr', {},
        el('td', {},
          el('div', { class: 'cell-main' }, el('a', { href: `/alerts/${a.id}` }, a.description || '(sem descrição)')),
          el('div', { class: 'cell-sub mono' }, a.alert_key)),
        el('td', {}, a.host.id
          ? el('a', { href: `/hosts/${a.host.id}` }, a.host.name)
          : na('sem host'),
        el('div', { class: 'cell-sub' }, a.host_groups.slice(0, 2).join(', '))),
        el('td', {}, el('span', { class: `sev ${sevClass(a.severity)}` }, a.severity)),
        el('td', {}, a.family ? el('a', { href: `/families/${a.family.id}` }, a.family.label) : na('—')),
        el('td', {},
          a.discovered ? el('span', { class: 'badge lld' }, 'LLD') : null, ' ',
          a.collision ? el('span', { class: 'badge collision' }, 'colisão') : null, ' ',
          a.dependencies ? el('span', { class: 'badge' }, `${a.dependencies} dep`) : null, ' ',
          a.tags ? el('span', { class: 'badge' }, `${a.tags} tags`) : null),
        el('td', {}, badgeProcedimento(a.procedure_status))))),
    paginador(dados.pagination, (p) => aplicarFiltro({ page: p })),
  );
});

/* ---------------------------------------------------------- detalhe alerta */
rota(/^\/alerts\/(.+)$/, async ([id]) => {
  const a = await api(`/api/alerts/${encodeURIComponent(id)}`);
  const c = a.condition;

  setView(
    cabecalho(a.identification.description || '(sem descrição)',
      `Trigger ${a.id} · coletado em ${a.collected_at}`,
      el('span', {}, el('a', { href: '/alerts' }, 'Alertas'), ' / ', a.id)),

    a.collision ? el('div', { class: 'note warn' },
      el('strong', {}, 'Alert key em colisão. '),
      'Esta chave agrupa triggers tecnicamente diferentes. Isso PODE ser duplicidade no Zabbix, mas também pode ser um par avisar/agir legítimo — ',
      el('a', { href: '/collisions' }, 'ver análise'), '.') : null,

    el('div', { class: 'grid-2' },
      el('section', { class: 'panel' }, el('h2', {}, 'Identificação'),
        el('dl', { class: 'kv' },
          el('dt', {}, 'alert_key'), el('dd', { class: 'mono' }, a.identification.alert_key),
          el('dt', {}, 'Estratégia da chave'), el('dd', {}, a.identification.alert_key_strategy),
          el('dt', {}, 'Escopo da chave'), el('dd', {},
            `${a.identification.alert_key_scope.type || '?'}: ${a.identification.alert_key_scope.name || '?'}`),
          el('dt', {}, 'source_hash'), el('dd', { class: 'mono' }, a.identification.source_hash),
          a.identification.event_name ? el('dt', {}, 'Nome do evento') : null,
          a.identification.event_name ? el('dd', {}, a.identification.event_name) : null,
          a.identification.alert_key_suggested ? el('dt', {}, 'Chave sugerida') : null,
          a.identification.alert_key_suggested ? el('dd', { class: 'mono' }, a.identification.alert_key_suggested) : null)),

      el('section', { class: 'panel' }, el('h2', {}, 'Origem'),
        el('dl', { class: 'kv' },
          el('dt', {}, 'Host'), el('dd', {}, a.origin.host.hostid
            ? el('a', { href: `/hosts/${a.origin.host.hostid}` }, a.origin.host.name || a.origin.host.host)
            : na()),
          el('dt', {}, 'Host groups'), el('dd', {}, a.origin.host_groups.length
            ? a.origin.host_groups.join(', ') : na('sem grupo')),
          el('dt', {}, 'Template'), el('dd', {}, a.origin.source_template
            || na('não resolvido pela coleta')),
          el('dt', {}, 'Origem do trigger'), el('dd', {}, a.origin.discovered
            ? el('span', {}, el('span', { class: 'badge lld' }, 'LLD'), ' descoberto por ',
              el('span', { class: 'mono' }, a.origin.discovery_rule?.name || '?'))
            : 'trigger direto no host'),
          a.origin.prototype_description ? el('dt', {}, 'Protótipo') : null,
          a.origin.prototype_description ? el('dd', { class: 'mono' }, a.origin.prototype_description) : null,
          el('dt', {}, 'Severidade'), el('dd', {},
            el('span', { class: `sev ${sevClass(a.severity.name)}` }, a.severity.name)),
          el('dt', {}, 'Estado'), el('dd', { class: 'muted' },
            `${a.state.status.name || '?'} · ${a.state.value.name || '?'}`)))),

    el('section', { class: 'panel' }, el('h2', {}, 'Condição'),
      el('div', { class: 'subtitle', style: 'margin-bottom:6px' },
        'Expressão do Zabbix, exibida como texto. A interface nunca a executa.'),
      el('pre', { class: 'expr' }, c.expression_expanded || c.expression_raw || '—'),
      c.recovery_expression ? el('div', {}, el('h2', {}, 'Recuperação'),
        el('pre', { class: 'expr' }, c.recovery_expression)) : null,
      el('dl', { class: 'kv', style: 'margin-top:10px' },
        el('dt', {}, 'Modo de recuperação'), el('dd', {}, c.recovery_mode.name || '—'),
        el('dt', {}, 'Fechamento manual'), el('dd', {}, c.manual_close ? 'permitido' : 'não'),
        c.opdata ? el('dt', {}, 'Dados operacionais') : null,
        c.opdata ? el('dd', { class: 'mono' }, c.opdata) : null)),

    el('div', { class: 'grid-2' },
      el('section', { class: 'panel' }, el('h2', {}, `Itens relacionados (${a.items.length})`),
        a.items.length ? tabela([{ label: 'Chave' }, { label: 'Nome' }, { label: 'Tipo' }],
          a.items.map((i) => el('tr', {},
            el('td', { class: 'mono' }, i.key_),
            el('td', {}, i.name),
            el('td', { class: 'cell-sub' }, `${i.value_type?.name || '?'}${i.units ? ' · ' + i.units : ''}`))))
          : na('nenhum item relacionado')),

      el('section', { class: 'panel' }, el('h2', {}, `Dependências (${a.dependencies.length})`),
        a.dependencies.length ? el('ul', {}, a.dependencies.map((d) => el('li', {},
          el('a', { href: `/alerts/${d.triggerid}` }, d.description), d.host ? ` (${d.host})` : '')))
          : na('sem dependências'))),

    el('div', { class: 'grid-2' },
      el('section', { class: 'panel' }, el('h2', {}, 'Comentário no Zabbix'),
        a.comments ? el('pre', { class: 'expr' }, a.comments) : na('sem comentário')),
      el('section', { class: 'panel' }, el('h2', {}, `Tags (${a.tags.length})`),
        a.tags.length ? el('div', { class: 'chips' }, a.tags.map((t) => el('span', { class: 'chip tag' },
          t.value ? `${t.tag}: ${t.value}` : t.tag))) : na('sem tags'))),

    a.family ? el('section', { class: 'panel' }, el('h2', {}, 'Família'),
      el('p', {}, el('a', { href: `/families/${a.family.id}` }, a.family.label),
        ' — ', num(a.family.alerts), ' alerta(s) em ', num(a.family.hosts), ' host(s). ',
        badgeProcedimento(a.family.procedure)),
      el('div', { class: 'subtitle' },
        'O procedimento é escrito no nível da família: um texto cobre todos os alertas dela.')) : null,

    blocoProcedimento(a.procedure, a.family?.id),
  );
});

/* ---------------------------------------------- procedimento (3 camadas) */
function blocoProcedimento(procedimento, alvoId, aoSalvar, tipo = 'family') {
  const operacional = procedimento.operational || {};
  const campos = [
    ['title', 'Título', 'text'], ['objective', 'Objetivo', 'textarea'],
    ['meaning', 'O que significa', 'textarea'], ['symptoms', 'Sintomas', 'lista'],
    ['probable_cause', 'Causa provável', 'textarea'],
    ['checks_before_action', 'Verificações antes de agir', 'lista'],
    ['actions', 'Ações', 'lista'], ['validation', 'Como validar', 'textarea'],
    ['resolution_criteria', 'Critério de resolução', 'textarea'],
    ['risks', 'Riscos', 'lista'], ['notes', 'Observações', 'textarea'],
  ];

  const somenteLeitura = !alvoId || !aoSalvar;
  const entradas = {};
  const form = el('form', { class: 'procedure' });

  if (!somenteLeitura) {
    const estado = el('select', { name: 'doc_status' },
      [['undocumented', 'Ausente'], ['pending_review', 'Rascunho'], ['documented', 'Validado'],
       ['reviewed', 'Revisado'], ['not_applicable', 'Não aplicável']]
        .map(([v, t]) => el('option', { value: v, selected: (procedimento.doc_status || 'undocumented') === v }, t)));
    entradas.doc_status = estado;
    form.append(el('label', {}, 'Estado do procedimento'), estado);

    for (const [nome, rotulo, tipo] of campos) {
      const valor = Array.isArray(operacional[nome]) ? operacional[nome].join('\n') : (operacional[nome] || '');
      const campo = tipo === 'text'
        ? el('input', { type: 'text', name: nome, value: valor })
        : el('textarea', { name: nome, rows: tipo === 'lista' ? 4 : 3 }, valor);
      entradas[nome] = { campo, lista: tipo === 'lista' };
      form.append(el('label', {}, rotulo + (tipo === 'lista' ? ' (um por linha)' : '')), campo);
    }

    const mensagem = el('div', { class: 'form-msg' });
    form.append(el('div', { class: 'form-actions' },
      el('button', { class: 'primary', type: 'submit' }, 'Salvar procedimento local'),
      el('span', { class: 'muted' }, 'Grava em docs/alerts/ — nunca no Zabbix.'), mensagem));

    form.addEventListener('submit', async (evento) => {
      evento.preventDefault();
      mensagem.className = 'form-msg';
      mensagem.textContent = 'Salvando…';
      const payload = { doc_status: entradas.doc_status.value };
      for (const [nome, { campo, lista }] of Object.entries(entradas)) {
        if (nome === 'doc_status') continue;
        const bruto = campo.value.trim();
        payload[nome] = lista ? bruto.split('\n').map((l) => l.trim()).filter(Boolean) : bruto;
      }
      try {
        const destino = tipo === 'rule'
          ? `/api/rules/${encodeURIComponent(alvoId)}/procedure`
          : `/api/procedures/${encodeURIComponent(alvoId)}`;
        const resposta = await fetch(destino, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ operational: payload, expected_revision: procedimento.revision }),
        });
        const dados = await resposta.json();
        if (!resposta.ok) throw new Error(dados.error || `HTTP ${resposta.status}`);
        mensagem.className = 'form-msg ok';
        mensagem.textContent = 'Salvo.';
        aoSalvar(dados);
      } catch (e) {
        mensagem.className = 'form-msg error';
        mensagem.textContent = e.message;
      }
    });
  }

  const observado = el('div', { class: 'layer layer-observed' },
    el('div', { class: 'layer-title' }, 'Dados observados no Zabbix'),
    el('p', { class: 'muted' }, 'Descrição, expressão, itens, tags e comentário vêm da coleta. São fato, não opinião — e ninguém os edita aqui.'));

  const humano = el('div', { class: 'layer layer-human' },
    el('div', { class: 'layer-title' }, 'Procedimento operacional validado'),
    somenteLeitura
      ? (procedimento.exists && procedimento.status !== 'missing'
        ? el('div', {}, badgeProcedimento(procedimento),
          el('dl', { class: 'kv', style: 'margin-top:8px' },
            campos.flatMap(([nome, rotulo]) => {
              const valor = operacional[nome];
              const texto = Array.isArray(valor) ? valor.join(' · ') : valor;
              return texto ? [el('dt', {}, rotulo), el('dd', {}, texto)] : [];
            })))
        : el('div', {}, badgeProcedimento('missing'),
          el('p', { class: 'muted' }, 'Nenhum procedimento escrito para esta família. Nada é inventado aqui: o estado é ausente até que uma pessoa escreva.'),
          alvoId ? el('a', { href: `/${tipo === 'rule' ? 'rules' : 'families'}/${alvoId}` },
            `Escrever na página da ${tipo === 'rule' ? 'regra' : 'família'} →`) : null))
      : form);

  const ia = el('div', { class: 'layer layer-ai' },
    el('div', { class: 'layer-title' }, 'Sugestão de IA'),
    el('p', { class: 'muted' }, procedimento.ai_suggestion
      ? JSON.stringify(procedimento.ai_suggestion)
      : 'Reservado. Nenhuma sugestão é gerada nesta fase — e uma sugestão nunca conta como procedimento: só vira oficial quando uma pessoa a escreve e assina.'));

  return el('section', { class: 'panel' },
    el('h2', {}, 'Procedimento'),
    el('div', { class: 'subtitle', style: 'margin-bottom:10px' },
      'As três camadas ficam separadas de propósito: observado ≠ validado ≠ sugerido.'),
    el('div', { class: 'layers' }, observado, humano, ia));
}

/* ------------------------------------------------- documentação: grupos */
const CONF_CLASS = { high: 'conf-high', medium: 'conf-medium', low: 'conf-low' };

function barraProgresso(pct) {
  return el('div', { class: 'progress' }, el('i', { style: `width:${Math.max(0, Math.min(100, pct))}%` }));
}

function linhaProgresso(regras) {
  return el('div', { class: 'progress-line' },
    barraProgresso(regras.progress),
    el('span', { class: 'muted' },
      `${num(regras.documented)}/${num(regras.active)} regras documentadas (${regras.progress}%)`));
}

rota(/^\/groups$/, async (_m, params) => {
  const dados = await api('/api/groups', params);
  const { form } = campoBusca(params, 'nome do grupo…');

  setView(
    cabecalho('Documentação por grupo',
      'Escolha o grupo que você vai documentar hoje — em vez de procurar entre milhares de alertas.'),
    form,
    el('div', { class: 'work-cards' }, dados.items.map((g) => el('a', {
      class: 'work-card', href: `/groups/${g.id}`,
    },
      el('h3', {}, g.name),
      el('div', { class: 'meta' },
        `${num(g.hosts)} hosts · ${num(g.alerts)} alertas · ${num(g.rules.total)} regras`),
      linhaProgresso(g.rules),
      el('div', { class: 'foot' },
        g.rules.pending
          ? el('span', { class: 'badge missing' }, `${num(g.rules.pending)} pendente(s)`)
          : el('span', { class: 'badge documented' }, 'tudo documentado'),
        g.rules.in_progress ? el('span', { class: 'badge draft' }, `${num(g.rules.in_progress)} em andamento`) : null)))),
    paginador(dados.pagination, (p) => aplicarFiltro({ page: p })),
  );
});

rota(/^\/groups\/([^/]+)$/, async ([id], params) => {
  const g = await api(`/api/groups/${encodeURIComponent(id)}`, params);
  const regras = g.rules_page;

  setView(
    cabecalho(g.name,
      `${num(g.hosts)} hosts · ${num(g.alerts)} alertas · ${num(g.rules.total)} regras operacionais`,
      el('span', {}, el('a', { href: '/groups' }, 'Grupos'), ' / ', g.name)),

    el('section', { class: 'panel' },
      el('h2', {}, 'Progresso da documentação'),
      linhaProgresso(g.rules),
      el('div', { class: 'chips', style: 'margin-top:10px' },
        el('span', { class: 'chip' }, `${num(g.rules.documented)} documentadas`),
        el('span', { class: 'chip' }, `${num(g.rules.in_progress)} em andamento`),
        el('span', { class: 'chip' }, `${num(g.rules.pending)} pendentes`),
        el('span', { class: 'chip' }, `${num(g.rules.confirmed)} confirmadas`))),

    el('div', { class: 'note' }, regras.note),
    el('h2', {}, 'Regras para documentar'),
    el('div', { class: 'work-cards' }, regras.items.map(cardRegra)),
    paginador(regras.pagination, (p) => aplicarFiltro({ page: p })),

    el('section', { class: 'panel', style: 'margin-top:18px' },
      el('h2', {}, `Hosts do grupo (${num(g.hosts)})`),
      el('div', { class: 'chips' }, g.hosts_list.map((h) =>
        el('a', { class: 'chip', href: `/hosts/${h.id}` }, `${h.name} (${num(h.alerts)})`)))),
  );
});

function cardRegra(r) {
  const proc = r.procedure || {};
  const acao = proc.status === 'missing' ? 'DOCUMENTAR'
    : proc.status === 'draft' ? 'CONTINUAR' : 'REVISAR';
  return el('a', { class: 'work-card', href: `/rules/${r.id}` },
    el('h3', {}, r.label),
    el('div', { class: 'meta' },
      `${num(r.alerts)} alertas · ${num(r.instances)} instâncias · ${num(r.families)} famílias técnicas`),
    el('div', { class: 'foot' },
      el('span', { class: `conf ${CONF_CLASS[r.confidence]}` }, `Confiança ${r.confidence_label}`),
      badgeProcedimento(proc),
      r.status !== 'candidate'
        ? el('span', { class: `status-pill status-${r.status}` }, rotuloStatus(r.status)) : null),
    el('div', {}, el('span', { class: 'cta', style: 'padding:6px 14px;font-size:13px' }, acao)));
}

const rotuloStatus = (s) => ({
  candidate: 'Sugerido', confirmed: 'Confirmado', ignored: 'Ignorado', split: 'Mantido separado',
}[s] || s);

/* -------------------------------------------------------- lista de regras */
rota(/^\/rules$/, async (_m, params) => {
  const dados = await api('/api/rules', params);
  const { form } = campoBusca(params, 'nome da regra…');
  form.append(
    seletor('Confiança', 'confidence', [['high', 'Alta'], ['medium', 'Média'], ['low', 'Baixa']], params),
    seletor('Decisão', 'status', [['candidate', 'Sugeridas'], ['confirmed', 'Confirmadas'],
      ['split', 'Mantidas separadas'], ['ignored', 'Ignoradas']], params),
    seletor('Procedimento', 'procedure', [['missing', 'Sem procedimento'], ['draft', 'Rascunho'],
      ['documented', 'Validado']], params));

  setView(
    cabecalho('Regras operacionais',
      `${num(dados.pagination.total)} de ${num(dados.facets.total_unfiltered)} regras`),
    el('div', { class: 'note' }, dados.note),
    el('div', { class: 'chips' },
      dados.facets.by_confidence.map((f) => el('a', {
        class: `chip ${params.confidence === f.confidence ? 'active' : ''}`,
        href: comFiltros({ confidence: f.confidence }),
      }, `${f.label}: ${num(f.value)}`))),
    form,
    el('div', { class: 'work-cards' }, dados.items.map(cardRegra)),
    paginador(dados.pagination, (p) => aplicarFiltro({ page: p })),
  );
});

/* --------------------------------------------------------- página da regra */
rota(/^\/rules\/([^/]+)$/, async ([id], params) => {
  const r = await api(`/api/rules/${encodeURIComponent(id)}`, params);
  const recarregar = () => render();

  setView(
    cabecalho(r.label, r.description,
      el('span', {}, el('a', { href: '/groups' }, 'Grupos'), ' / ',
        el('a', { href: `/groups/${r.group.id}` }, r.group.name), ' / ', r.label)),

    el('div', { class: 'scope-banner' },
      el('span', {}, el('strong', {}, num(r.alerts)), ' alertas'),
      el('span', {}, el('strong', {}, num(r.instances)), ' instâncias'),
      el('span', {}, el('strong', {}, num(r.families)), ' famílias técnicas'),
      el('span', {}, el('strong', {}, num(r.dependencies)), ' dependências'),
      el('span', {}, el('strong', {}, num(r.hosts)), ' hosts'),
      el('span', { class: `conf ${CONF_CLASS[r.confidence]}` }, `Confiança ${r.confidence_label}`),
      badgeProcedimento(r.procedure)),

    blocoDecisao(r, recarregar),

    el('section', { class: 'panel' },
      el('h2', {}, 'Por que estes alertas foram agrupados?'),
      el('div', { class: 'why' },
        el('ul', {}, r.reasons.map((m) => el('li', {}, m))),
        r.evidence_samples.length
          ? el('div', { style: 'margin-top:10px' },
            el('div', { class: 'cell-sub' }, 'Exemplos:'),
            el('ul', {}, r.evidence_samples.map((e) => el('li', { class: 'muted' }, e))))
          : null,
        el('div', { class: 'disclaimer' },
          'Agrupamento sugerido por heurística determinística e local (chaves de item, descrições e '
          + 'dependências entre triggers). Não é um diagnóstico e não afirma que estes alertas têm a mesma causa.'))),

    el('section', { class: 'panel' },
      el('h2', {}, 'O que o Zabbix está monitorando'),
      el('div', { class: 'chips' }, r.item_prefixes.map((i) =>
        el('span', { class: 'chip tag' }, `${i.prefix}* (${num(i.alerts)})`))),
      el('div', { class: 'subtitle', style: 'margin-top:8px' },
        'Somente fatos observados na coleta: as chaves de item que estes alertas leem.')),

    el('div', { class: 'grid-2' },
      el('section', { class: 'panel' },
        el('h2', {}, `Instâncias (${num(r.instances)})`),
        el('div', { class: 'subtitle', style: 'margin-bottom:8px' },
          'Onde a regra está aplicada. A documentação pertence à regra; a instância só diz onde.'),
        r.instances_page.total
          ? el('div', { class: 'instances' }, r.instances_page.items.map((i) =>
            el('a', { class: 'instance', href: `/rules/${r.id}/instances/${encodeURIComponent(i.name)}` },
              `${i.name} (${num(i.alerts)})`)))
          : na('a regra se aplica ao host inteiro'),
        r.instances_page.pagination.pages > 1
          ? paginador(r.instances_page.pagination, (p) => aplicarFiltro({ instance_page: p })) : null),

      el('section', { class: 'panel' },
        el('h2', {}, `Hosts afetados (${num(r.hosts)})`),
        el('div', { class: 'chips' }, r.hosts_list.map((h) =>
          el('a', { class: 'chip', href: `/hosts/${h.id}` }, h.name))))),

    el('section', { class: 'panel' },
      el('h2', {}, `Famílias técnicas relacionadas (${num(r.families)})`),
      el('div', { class: 'subtitle', style: 'margin-bottom:8px' },
        'A origem técnica no Zabbix. Elas continuam existindo — a regra apenas as reúne numa unidade de documentação.'),
      tabela([{ label: 'Família técnica' }, { label: 'Origem' }, { label: 'Alertas', num: true }],
        r.families_list.map((f) => el('tr', {},
          el('td', {}, el('a', { href: `/families/${f.id}` }, f.label)),
          el('td', { class: 'cell-sub' }, f.origin),
          el('td', { class: 'num' }, num(f.alerts)))))),

    r.dependencies_list.length
      ? el('section', { class: 'panel' }, el('h2', {}, `Dependências (${r.dependencies_list.length})`),
        el('ul', {}, r.dependencies_list.slice(0, 20).map((d) => el('li', {},
          el('a', { href: `/alerts/${d.from.id}` }, d.from.description), ' → ', d.to.description,
          d.internal ? el('span', { class: 'badge', style: 'margin-left:6px' }, 'dentro da regra') : null))))
      : null,

    el('section', { class: 'panel' },
      el('h2', {}, `Alertas (${num(r.alerts)})`),
      tabela([{ label: 'Alerta' }, { label: 'Host' }, { label: 'Severidade' }],
        r.alerts_page.items.map((a) => el('tr', {},
          el('td', {}, el('a', { href: `/alerts/${a.id}` }, a.description || '(sem descrição)')),
          el('td', {}, a.host.id ? el('a', { href: `/hosts/${a.host.id}` }, a.host.name) : na('—')),
          el('td', {}, el('span', { class: `sev ${sevClass(a.severity)}` }, a.severity))))),
      paginador(r.alerts_page.pagination, (p) => aplicarFiltro({ page: p }))),

    blocoProcedimento(r.procedure, r.id, recarregar, 'rule'),
  );
});

/* ------------------------------------------------- instância de uma regra */
rota(/^\/rules\/([^/]+)\/instances\/(.+)$/, async ([id, instancia], params) => {
  const [r, alertas] = await Promise.all([
    api(`/api/rules/${encodeURIComponent(id)}`),
    api(`/api/rules/${encodeURIComponent(id)}/alerts`, { ...params, instance: instancia }),
  ]);
  setView(
    cabecalho(instancia, `Instância de “${r.label}” · ${num(alertas.pagination.total)} alertas`,
      el('span', {}, el('a', { href: `/groups/${r.group.id}` }, r.group.name), ' / ',
        el('a', { href: `/rules/${r.id}` }, r.label), ' / ', instancia)),
    el('div', { class: 'note' },
      'A documentação pertence à regra, não a esta instância. ',
      el('a', { href: `/rules/${r.id}` }, 'Ver o procedimento da regra →')),
    tabela([{ label: 'Alerta' }, { label: 'Host' }, { label: 'Severidade' }, { label: 'Família técnica' }],
      alertas.items.map((a) => el('tr', {},
        el('td', {}, el('a', { href: `/alerts/${a.id}` }, a.description || '(sem descrição)')),
        el('td', {}, a.host.id ? el('a', { href: `/hosts/${a.host.id}` }, a.host.name) : na('—')),
        el('td', {}, el('span', { class: `sev ${sevClass(a.severity)}` }, a.severity)),
        el('td', {}, a.family ? el('a', { href: `/families/${a.family.id}` }, a.family.label) : na('—'))))),
    paginador(alertas.pagination, (p) => aplicarFiltro({ page: p })),
  );
});

/* --------------------------------------------- confirmar / ignorar / separar */
function blocoDecisao(regra, aoDecidir) {
  const mensagem = el('span', { class: 'form-msg' });
  const decidir = async (status) => {
    mensagem.className = 'form-msg';
    mensagem.textContent = 'Salvando…';
    try {
      const resposta = await fetch(`/api/rules/${encodeURIComponent(regra.id)}/decision`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      const dados = await resposta.json();
      if (!resposta.ok) throw new Error(dados.error || `HTTP ${resposta.status}`);
      aoDecidir();
    } catch (e) {
      mensagem.className = 'form-msg error';
      mensagem.textContent = e.message;
    }
  };

  return el('section', { class: 'panel' },
    el('h2', {}, 'Este agrupamento faz sentido?'),
    el('div', { class: 'subtitle' },
      'O sistema sugeriu com base em evidências técnicas. A decisão é sua — e é reversível.'),
    el('div', { class: 'decide' },
      el('span', { class: `status-pill status-${regra.status}` }, rotuloStatus(regra.status)),
      el('button', { class: regra.status === 'confirmed' ? '' : 'primary',
        onclick: () => decidir('confirmed') }, 'Confirmar agrupamento'),
      el('button', { onclick: () => decidir('split') }, 'Manter separado'),
      el('button', { onclick: () => decidir('ignored') }, 'Ignorar sugestão'),
      regra.status !== 'candidate'
        ? el('button', { onclick: () => decidir('candidate') }, 'Desfazer') : null,
      mensagem),
    regra.decided_at
      ? el('div', { class: 'muted', style: 'margin-top:6px' },
        `Decidido em ${regra.decided_at}${regra.decided_by ? ' por ' + regra.decided_by : ''}`)
      : null);
}

/* ---------------------------------------------------------------- famílias */
rota(/^\/families$/, async (_m, params) => {
  const dados = await api('/api/families', params);
  const { form } = campoBusca(params, 'nome da família…');
  form.append(
    seletor('Procedimento', 'procedure', [
      ['missing', 'Sem procedimento'], ['draft', 'Rascunho'], ['documented', 'Validado'],
      ['needs_review', 'Precisa revisão']], params),
    seletor('Origem', 'discovered', [['1', 'Somente LLD'], ['0', 'Somente não-LLD']], params),
    seletor('Abrangência', 'multi_host', [['1', 'Vários hosts'], ['0', 'Host único']], params));

  setView(
    cabecalho('Famílias de alertas',
      `${num(dados.pagination.total)} de ${num(dados.facets.total_unfiltered)} famílias · ordenadas por quantidade de alertas`),
    el('div', { class: 'note' },
      'Uma família é uma regra operacional. Milhares de triggers de LLD podem ser uma família só — e um procedimento cobre todos eles.'),
    form,
    tabela([{ label: 'Família' }, { label: 'Origem' }, { label: 'Alertas', num: true },
            { label: 'Hosts', num: true }, { label: 'Expressões', num: true },
            { label: 'Severidades' }, { label: 'Procedimento' }],
      dados.items.map((f) => el('tr', {},
        el('td', {}, el('a', { href: `/families/${f.id}` }, f.label)),
        el('td', { class: 'cell-sub' }, f.origin),
        el('td', { class: 'num' }, num(f.alerts)),
        el('td', { class: 'num' }, num(f.hosts)),
        el('td', { class: 'num' }, num(f.distinct_expressions)),
        el('td', {}, severidadesInline(f.severities)),
        el('td', {}, badgeProcedimento(f.procedure))))),
    paginador(dados.pagination, (p) => aplicarFiltro({ page: p })),
  );
});

rota(/^\/families\/(.+)$/, async ([id], params) => {
  const f = await api(`/api/families/${encodeURIComponent(id)}`, params);
  const recarregar = () => render();

  setView(
    cabecalho(f.label, `${f.origin} · ${num(f.alerts)} alertas em ${num(f.hosts)} host(s)`,
      el('span', {}, el('a', { href: '/families' }, 'Famílias'), ' / ', f.id)),

    el('div', { class: 'grid-2' },
      el('section', { class: 'panel' }, el('h2', {}, 'Resumo'),
        el('dl', { class: 'kv' },
          el('dt', {}, 'Chave da família'), el('dd', { class: 'mono' }, f.key),
          el('dt', {}, 'Alertas'), el('dd', {}, num(f.alerts)),
          el('dt', {}, 'Hosts'), el('dd', {}, num(f.hosts)),
          el('dt', {}, 'Host groups'), el('dd', {}, f.host_groups.join(', ') || na('—')),
          el('dt', {}, 'Expressões distintas'), el('dd', {}, num(f.distinct_expressions)),
          el('dt', {}, 'Dependências'), el('dd', {}, num(f.dependencies)),
          el('dt', {}, 'Procedimento'), el('dd', {}, badgeProcedimento(f.procedure)))),
      el('section', { class: 'panel' }, el('h2', {}, 'Severidades'),
        barrasSeveridade(f.severities, f.alerts))),

    el('div', { class: 'grid-2' },
      el('section', { class: 'panel' }, el('h2', {}, `Hosts afetados (${num(f.hosts)})`),
        f.hosts_list.length
          ? el('div', { class: 'chips' }, f.hosts_list.slice(0, 60).map((h) =>
            el('a', { class: 'chip', href: `/hosts/${h.id}` }, h.name)))
          : na('nenhum host'),
        f.hosts_list.length > 60
          ? el('div', { class: 'muted', style: 'margin-top:6px' }, `… e mais ${num(f.hosts_list.length - 60)} host(s)`)
          : null),
      el('section', { class: 'panel' }, el('h2', {}, `Expressões distintas (${f.expressions.length})`),
        f.expressions.slice(0, 6).map((e) => el('div', { style: 'margin-bottom:8px' },
          el('div', { class: 'cell-sub' }, `${num(e.alerts)} alerta(s)`),
          el('pre', { class: 'expr' }, e.example || e.signature))))),

    el('div', { class: 'grid-2' },
      el('section', { class: 'panel' }, el('h2', {}, 'Chaves de item mais comuns'),
        f.item_keys.length ? el('div', { class: 'chips' },
          f.item_keys.slice(0, 20).map((i) => el('span', { class: 'chip tag' }, `${i.key} (${num(i.alerts)})`)))
          : na('nenhum item')),
      el('section', { class: 'panel' }, el('h2', {}, 'Tags'),
        f.tags.length ? el('div', { class: 'chips' },
          f.tags.slice(0, 20).map((t) => el('span', { class: 'chip tag' }, `${t.tag} (${num(t.alerts)})`)))
          : na('sem tags'))),

    f.comments.length ? el('section', { class: 'panel' }, el('h2', {}, 'Comentários do Zabbix'),
      f.comments.map((c) => el('div', { style: 'margin-bottom:8px' },
        el('div', { class: 'cell-sub' }, `${num(c.alerts)} alerta(s)`),
        el('pre', { class: 'expr' }, c.text)))) : null,

    blocoProcedimento(f.procedure, f.id, recarregar),

    el('section', { class: 'panel' }, el('h2', {}, `Alertas da família (${num(f.alerts)})`),
      tabela([{ label: 'Alerta' }, { label: 'Host' }, { label: 'Severidade' }, { label: 'Sinais' }],
        f.alerts_page.items.map((a) => el('tr', {},
          el('td', {}, el('a', { href: `/alerts/${a.id}` }, a.description || '(sem descrição)')),
          el('td', {}, a.host.id ? el('a', { href: `/hosts/${a.host.id}` }, a.host.name) : na('—')),
          el('td', {}, el('span', { class: `sev ${sevClass(a.severity)}` }, a.severity)),
          el('td', {}, a.collision ? el('span', { class: 'badge collision' }, 'colisão') : null, ' ',
            a.dependencies ? el('span', { class: 'badge' }, `${a.dependencies} dep`) : null)))),
      paginador(f.alerts_page.pagination, (p) => aplicarFiltro({ page: p }))),
  );
});

/* ------------------------------------------------------------------- hosts */
rota(/^\/hosts$/, async (_m, params) => {
  const dados = await api('/api/hosts', params);
  const { form } = campoBusca(params, 'nome do host…');
  setView(
    cabecalho('Hosts', `${num(dados.pagination.total)} de ${num(dados.facets.total_unfiltered)} hosts`),
    form,
    tabela([{ label: 'Host' }, { label: 'Host groups' }, { label: 'Alertas', num: true },
            { label: 'Famílias', num: true }, { label: 'Críticos', num: true },
            { label: 'LLD', num: true }, { label: 'Sem procedimento', num: true }],
      dados.items.map((h) => el('tr', {},
        el('td', {}, el('a', { href: `/hosts/${h.id}` }, h.name),
          h.technical_name && h.technical_name !== h.name
            ? el('div', { class: 'cell-sub mono' }, h.technical_name) : null),
        el('td', { class: 'cell-sub' }, h.host_groups.join(', ') || '—'),
        el('td', { class: 'num' }, num(h.alerts)),
        el('td', { class: 'num' }, num(h.families)),
        el('td', { class: 'num' }, h.critical ? el('span', { class: 'sev sev-high' }, num(h.critical)) : '0'),
        el('td', { class: 'num' }, num(h.discovered)),
        el('td', { class: 'num' }, num(h.procedures_missing))))),
    paginador(dados.pagination, (p) => aplicarFiltro({ page: p })),
  );
});

rota(/^\/hosts\/(.+)$/, async ([id], params) => {
  const h = await api(`/api/hosts/${encodeURIComponent(id)}`, params);
  const inventario = Object.entries(h.inventory || {});
  setView(
    cabecalho(h.name, `${num(h.alerts)} alertas · ${num(h.families)} famílias · ${num(h.procedures_missing)} sem procedimento`,
      el('span', {}, el('a', { href: '/hosts' }, 'Hosts'), ' / ', h.id)),

    el('div', { class: 'grid-2' },
      el('section', { class: 'panel' }, el('h2', {}, 'Informações'),
        el('dl', { class: 'kv' },
          el('dt', {}, 'Nome técnico'), el('dd', { class: 'mono' }, h.technical_name || na('—')),
          el('dt', {}, 'Status'), el('dd', {}, h.status || na('—')),
          el('dt', {}, 'Host groups'), el('dd', {},
            h.host_groups.length
              ? h.host_groups.map((g, i) => el('span', {}, i ? ', ' : '',
                el('a', { href: `/host-groups/${slug(g)}` }, g)))
              : na('sem grupo')),
          ...inventario.flatMap(([k, v]) => [el('dt', {}, k), el('dd', {}, v)]))),
      el('section', { class: 'panel' }, el('h2', {}, 'Severidades'),
        barrasSeveridade(h.severities, h.alerts))),

    h.rules_list.length ? el('section', {},
      el('h2', {}, `Regras operacionais neste host (${num(h.rules)})`),
      el('div', { class: 'subtitle', style: 'margin-bottom:8px' },
        'A unidade de documentação. O host é o contexto onde estas regras se aplicam.'),
      el('div', { class: 'work-cards' }, h.rules_list.slice(0, 12).map(cardRegra))) : null,

    el('section', { class: 'panel' }, el('h2', {}, `Famílias técnicas neste host (${num(h.families)})`),
      tabela([{ label: 'Família' }, { label: 'Alertas', num: true }, { label: 'Procedimento' }],
        h.families_list.map((f) => el('tr', {},
          el('td', {}, el('a', { href: `/families/${f.id}` }, f.label)),
          el('td', { class: 'num' }, num(f.alerts)),
          el('td', {}, badgeProcedimento(f.procedure)))))),

    el('div', { class: 'grid-2' },
      el('section', { class: 'panel' }, el('h2', {}, `Itens relacionados (${h.items.length})`),
        h.items.length ? el('div', { class: 'chips' },
          h.items.slice(0, 40).map((i) => el('span', { class: 'chip tag' }, i.key_)))
          : na('nenhum item')),
      el('section', { class: 'panel' }, el('h2', {}, `Dependências (${h.dependencies.length})`),
        h.dependencies.length ? el('ul', {}, h.dependencies.slice(0, 20).map((d) => el('li', {},
          d.from, ' → ', d.description))) : na('sem dependências'))),

    el('section', { class: 'panel' }, el('h2', {}, `Alertas (${num(h.alerts)})`),
      tabela([{ label: 'Alerta' }, { label: 'Severidade' }, { label: 'Família' }, { label: 'Procedimento' }],
        h.alerts_page.items.map((a) => el('tr', {},
          el('td', {}, el('a', { href: `/alerts/${a.id}` }, a.description || '(sem descrição)')),
          el('td', {}, el('span', { class: `sev ${sevClass(a.severity)}` }, a.severity)),
          el('td', {}, a.family ? el('a', { href: `/families/${a.family.id}` }, a.family.label) : na('—')),
          el('td', {}, badgeProcedimento(a.procedure_status))))),
      paginador(h.alerts_page.pagination, (p) => aplicarFiltro({ page: p }))),
  );
});

const slug = (texto) => String(texto).normalize('NFKD').replace(/[̀-ͯ]/g, '')
  .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

/* ------------------------------------------------------------- host groups */
rota(/^\/host-groups$/, async (_m, params) => {
  const dados = await api('/api/host-groups', params);
  const { form } = campoBusca(params, 'nome do grupo…');
  setView(
    cabecalho('Host groups', `${num(dados.pagination.total)} grupos`),
    el('div', { class: 'note' },
      'Um host pode estar em vários grupos: cada grupo conta os alertas dos seus próprios hosts. Somar os grupos NÃO dá o total do ambiente.'),
    form,
    tabela([{ label: 'Grupo' }, { label: 'Hosts', num: true }, { label: 'Alertas', num: true },
            { label: 'Famílias', num: true }, { label: 'Severidades' }],
      dados.items.map((g) => el('tr', {},
        el('td', {}, el('a', { href: `/host-groups/${g.id}` }, g.name)),
        el('td', { class: 'num' }, num(g.hosts)),
        el('td', { class: 'num' }, num(g.alerts)),
        el('td', { class: 'num' }, num(g.families)),
        el('td', {}, severidadesInline(g.severities))))),
    paginador(dados.pagination, (p) => aplicarFiltro({ page: p })),
  );
});

rota(/^\/host-groups\/(.+)$/, async ([id], params) => {
  const g = await api(`/api/host-groups/${encodeURIComponent(id)}`, params);
  const { form } = campoBusca(params, 'buscar dentro do grupo…');
  setView(
    cabecalho(g.name, `${num(g.hosts)} hosts · ${num(g.alerts)} alertas · ${num(g.families)} famílias`,
      el('span', {}, el('a', { href: '/host-groups' }, 'Host groups'), ' / ', g.id)),

    el('div', { class: 'grid-2' },
      el('section', { class: 'panel' }, el('h2', {}, 'Severidades'), barrasSeveridade(g.severities, g.alerts)),
      el('section', { class: 'panel' }, el('h2', {}, `Hosts (${num(g.hosts)})`),
        tabela([{ label: 'Host' }, { label: 'Alertas', num: true }, { label: 'Sem procedimento', num: true }],
          g.hosts_list.map((h) => el('tr', {},
            el('td', {}, el('a', { href: `/hosts/${h.id}` }, h.name)),
            el('td', { class: 'num' }, num(h.alerts)),
            el('td', { class: 'num' }, num(h.procedures_missing))))))),

    el('section', { class: 'panel' }, el('h2', {}, `Famílias no grupo (${num(g.families)})`),
      tabela([{ label: 'Família' }, { label: 'Alertas', num: true }, { label: 'Hosts', num: true }, { label: 'Procedimento' }],
        g.families_list.map((f) => el('tr', {},
          el('td', {}, el('a', { href: `/families/${f.id}` }, f.label)),
          el('td', { class: 'num' }, num(f.alerts)),
          el('td', { class: 'num' }, num(f.hosts)),
          el('td', {}, badgeProcedimento(f.procedure)))))),

    el('section', { class: 'panel' }, el('h2', {}, 'Alertas do grupo'),
      form,
      tabela([{ label: 'Alerta' }, { label: 'Host' }, { label: 'Severidade' }, { label: 'Procedimento' }],
        g.alerts_page.items.map((a) => el('tr', {},
          el('td', {}, el('a', { href: `/alerts/${a.id}` }, a.description || '(sem descrição)')),
          el('td', {}, a.host.id ? el('a', { href: `/hosts/${a.host.id}` }, a.host.name) : na('—')),
          el('td', {}, el('span', { class: `sev ${sevClass(a.severity)}` }, a.severity)),
          el('td', {}, badgeProcedimento(a.procedure_status))))),
      paginador(g.alerts_page.pagination, (p) => aplicarFiltro({ page: p }))),
  );
});

/* ---------------------------------------------------------- procedimentos */
rota(/^\/procedures$/, async (_m, params) => {
  const dados = await api('/api/procedures', params);
  const { form } = campoBusca(params, 'buscar família…');
  setView(
    cabecalho('Procedimentos', 'O conhecimento operacional é escrito no nível da família.'),
    el('div', { class: 'note' },
      'Dados observados, procedimento validado e sugestão de IA são três coisas diferentes e não se misturam. ',
      'Um procedimento só existe quando uma pessoa o escreve — nada é gerado automaticamente.'),
    el('div', { class: 'chips' },
      el('a', { class: `chip ${!params.status ? 'active' : ''}`, href: comFiltros({ status: '' }) }, 'Todos'),
      dados.facets.by_status.map((s) => el('a', {
        class: `chip ${params.status === s.status ? 'active' : ''}`,
        href: comFiltros({ status: s.status }),
      }, `${s.label} (${num(s.value)})`))),
    form,
    tabela([{ label: 'Família' }, { label: 'Origem' }, { label: 'Alertas', num: true },
            { label: 'Hosts', num: true }, { label: 'Estado' }, { label: 'Revisão' }],
      dados.items.map((f) => el('tr', {},
        el('td', {}, el('a', { href: `/families/${f.id}` }, f.label)),
        el('td', { class: 'cell-sub' }, f.origin),
        el('td', { class: 'num' }, num(f.alerts)),
        el('td', { class: 'num' }, num(f.hosts)),
        el('td', {}, badgeProcedimento(f.procedure)),
        el('td', { class: 'cell-sub' }, f.procedure.last_modified_at || '—')))),
    paginador(dados.pagination, (p) => aplicarFiltro({ page: p })),
  );
});

/* --------------------------------------------------------------- colisões */
rota(/^\/collisions$/, async (_m, params) => {
  const dados = await api('/api/collisions', params);
  setView(
    cabecalho('Colisões de alert_key', `${num(dados.pagination.total)} caso(s) para análise`),
    el('div', { class: 'note warn' }, dados.note),
    dados.items.map((c) => el('section', { class: 'panel' },
      el('h2', { class: 'mono' }, c.alert_key),
      el('div', { class: 'subtitle' },
        `${num(c.triggers)} triggers · ${c.hosts.length} host(s) · ${(c.reasons || []).join(', ')}`),
      el('dl', { class: 'kv', style: 'margin-top:8px' },
        el('dt', {}, 'Descrições'), el('dd', {}, c.descriptions.join(' · ')),
        el('dt', {}, 'Hosts'), el('dd', {}, c.hosts.join(', ') || na('—')),
        el('dt', {}, 'Severidades'), el('dd', {}, c.severities.join(', ')),
        el('dt', {}, 'Chave sugerida'), el('dd', { class: 'mono' }, c.suggested_key_pattern || na('—'))),
      el('h2', {}, 'Triggers envolvidos'),
      tabela([{ label: 'Trigger' }, { label: 'Host' }, { label: 'Severidade' }, { label: 'Expressão' }],
        (c.occurrences || []).map((o) => el('tr', {},
          el('td', {}, el('a', { href: `/alerts/${o.triggerid}` }, o.triggerid)),
          el('td', {}, o.host),
          el('td', {}, el('span', { class: `sev ${sevClass(o.priority)}` }, o.priority)),
          el('td', {}, el('pre', { class: 'expr' }, o.expression_expanded || o.expression_signature))))))),
    paginador(dados.pagination, (p) => aplicarFiltro({ page: p })),
  );
});

/* ----------------------------------------------------------------- status */
rota(/^\/status$/, async () => {
  const s = await api('/api/status');
  atualizarBadgeSnapshot(s.snapshot);
  const c = s.collection || {};
  const redacao = s.snapshot.redaction || {};

  setView(
    cabecalho('Status da coleta', escopoTexto(s.snapshot)),
    el('div', { class: 'note' }, s.note),
    el('div', { class: 'scope-banner' },
      el('span', {}, 'Coleta: ', el('strong', {}, s.snapshot.scope_label),
        ` — ${num(s.environment.alerts)} alertas, ${num(s.environment.hosts)} hosts, `
        + `${num(s.environment.host_groups)} grupos`),
      el('span', {}, 'Escopo operacional: ', el('strong', {}, s.scope.label),
        ` — ${num(s.scope.alerts_in_scope)} alertas`),
      s.scope.is_everything ? null
        : el('span', { class: 'out' }, `${num(s.scope.alerts_out_of_scope)} fora do escopo`)),
    el('div', { class: 'subtitle', style: 'margin:-6px 0 14px' },
      'Os números abaixo são do AMBIENTE COLETADO — a coleta não é filtrada por escopo.'),
    s.snapshot.partial ? el('div', { class: 'note warn' },
      'Snapshot PARCIAL: objetos ficaram de fora da coleta.') : null,
    !s.snapshot.complete_environment ? el('div', { class: 'note warn' },
      'Este snapshot NÃO cobre o ambiente inteiro — apenas o escopo indicado acima.') : null,

    el('div', { class: 'cards' },
      Object.entries(s.counts).map(([chave, valor]) => el('div', { class: 'card' },
        el('div', { class: 'card-value' }, num(valor)),
        el('div', { class: 'card-label' }, chave)))),

    el('div', { class: 'grid-2', style: 'margin-top:14px' },
      el('section', { class: 'panel' }, el('h2', {}, 'Snapshot em uso'),
        el('dl', { class: 'kv' },
          el('dt', {}, 'Nome'), el('dd', { class: 'mono' }, s.snapshot.name),
          el('dt', {}, 'Caminho'), el('dd', { class: 'mono' }, s.snapshot.path),
          el('dt', {}, 'Escopo'), el('dd', {}, s.snapshot.scope_label),
          el('dt', {}, 'Ambiente inteiro'), el('dd', {}, s.snapshot.complete_environment ? 'sim' : 'não'),
          el('dt', {}, 'Versão do Zabbix'), el('dd', {}, s.snapshot.zabbix_version || na('—')),
          s.merge && s.merge.sources ? el('dt', {}, 'Consolidado de') : null,
          s.merge && s.merge.sources ? el('dd', {}, `${s.merge.sources.length} snapshots`) : null)),

      el('section', { class: 'panel' }, el('h2', {}, 'Execução da coleta'),
        el('dl', { class: 'kv' },
          el('dt', {}, 'Duração'), el('dd', {}, c.duration_seconds != null ? `${c.duration_seconds}s` : na('—')),
          el('dt', {}, 'Tamanho de página'), el('dd', {}, c.page_size ?? na('—')),
          el('dt', {}, 'Páginas'), el('dd', {}, num(c.pages)),
          el('dt', {}, 'Retries'), el('dd', {}, num(c.retries)),
          el('dt', {}, 'Lotes reduzidos'), el('dd', {}, num((c.batch_reductions || []).length)),
          el('dt', {}, 'Objetos não coletados'), el('dd', {}, num((c.failed_objects || []).length)),
          el('dt', {}, 'Segredos redigidos'), el('dd', {},
            redacao.enabled === false
              ? el('span', { class: 'sev sev-high' }, 'redação DESLIGADA')
              : num(redacao.values_redacted || 0))))),

    el('section', { class: 'panel' }, el('h2', {}, 'Escopos operacionais'),
      el('div', { class: 'subtitle', style: 'margin-bottom:8px' },
        'Configurados em scopes.json. O escopo filtra a VISÃO, nunca o snapshot — '
        + 'trocar de escopo não altera nenhum dado coletado.'),
      tabela([{ label: 'Escopo' }, { label: 'Modo' }, { label: 'Regra' }],
        (s.scopes || []).map((e) => el('tr', { class: e.id === s.scope.id ? '' : 'muted' },
          el('td', {}, el('a', { href: comFiltrosEscopo(e.id) }, e.label),
            e.id === s.scope.id ? el('span', { class: 'badge documented', style: 'margin-left:6px' }, 'ativo') : null,
            e.is_default ? el('span', { class: 'badge', style: 'margin-left:6px' }, 'padrão') : null),
          el('td', { class: 'cell-sub' }, e.is_everything ? 'sem filtro'
            : e.mode === 'include' ? 'somente os listados' : 'tudo menos os listados'),
          el('td', { class: 'cell-sub mono' },
            [...(e.exclude_hosts || []), ...(e.exclude_host_patterns || []),
             ...(e.include_hosts || []), ...(e.include_host_patterns || [])].join(', ') || '—'))))),

    el('section', { class: 'panel' }, el('h2', {}, 'Snapshots disponíveis'),
      tabela([{ label: 'Snapshot' }, { label: 'Tipo' }, { label: 'Tamanho', num: true }],
        (s.available_snapshots || []).map((sn) => el('tr', {},
          el('td', { class: 'mono' }, sn.name, sn.name === s.snapshot.name
            ? el('span', { class: 'badge documented', style: 'margin-left:6px' }, 'em uso') : null),
          el('td', {}, sn.partial ? 'parcial' : sn.merged ? 'consolidado' : 'coleta'),
          el('td', { class: 'num' }, `${(sn.size_bytes / 1048576).toFixed(1)} MB`))))),
  );
});

/* ----------------------------------------------------------- busca global */
const inputBusca = document.getElementById('search-input');
const caixaBusca = document.getElementById('search-results');
let timerBusca;

const esconderBusca = () => { caixaBusca.hidden = true; caixaBusca.replaceChildren(); };

inputBusca.addEventListener('input', () => {
  clearTimeout(timerBusca);
  const termo = inputBusca.value.trim();
  if (termo.length < 2) return esconderBusca();
  timerBusca = setTimeout(async () => {
    try {
      const dados = await api('/api/search', { q: termo, limit: 6 });
      // Existem resultados além do escopo? Dizer "nada encontrado" quando há
      // 8.000 fora seria o pior tipo de silêncio.
      const aviso = dados.out_of_scope_alerts
        ? el('a', { class: 'search-item', href: comFiltrosEscopo('all') },
          el('div', {}, `+${num(dados.out_of_scope_alerts)} alerta(s) fora do escopo `,
            el('strong', {}, dados.scope?.label || '')),
          el('small', {}, 'clique para buscar no ambiente inteiro'))
        : null;

      if (!dados.groups.length) {
        caixaBusca.replaceChildren(
          el('div', { class: 'search-item muted' },
            `Nada encontrado para "${termo}" no escopo ${dados.scope?.label || 'atual'}`),
          aviso);
        caixaBusca.hidden = false;
        return;
      }
      caixaBusca.replaceChildren(...[aviso].filter(Boolean), ...dados.groups.flatMap((g) => [
        el('div', { class: 'search-group-title' }, `${g.label} (${num(g.total)})`),
        ...g.items.map((item) => linkResultado(g.kind, item)),
        g.total > g.items.length
          ? el('a', { class: 'search-item muted', href: linkTodos(g.kind, termo) },
            `Ver todos os ${num(g.total)} resultados →`)
          : null,
      ].filter(Boolean)));
      caixaBusca.hidden = false;
    } catch { esconderBusca(); }
  }, 180);
});

function linkResultado(tipo, item) {
  if (tipo === 'alerts') {
    return el('a', { class: 'search-item', href: `/alerts/${item.id}` },
      el('div', {}, item.description || '(sem descrição)'),
      el('small', {}, `${item.host.name || 'sem host'} · ${item.severity}`));
  }
  if (tipo === 'families') {
    return el('a', { class: 'search-item', href: `/families/${item.id}` },
      el('div', {}, item.label), el('small', {}, `${num(item.alerts)} alertas · ${item.origin}`));
  }
  if (tipo === 'hosts') {
    return el('a', { class: 'search-item', href: `/hosts/${item.id}` },
      el('div', {}, item.name), el('small', {}, `${num(item.alerts)} alertas`));
  }
  if (tipo === 'host_groups') {
    return el('a', { class: 'search-item', href: `/host-groups/${item.id}` },
      el('div', {}, item.name), el('small', {}, `${num(item.alerts)} alertas · ${num(item.hosts)} hosts`));
  }
  return el('a', { class: 'search-item', href: `/families/${item.id}` },
    el('div', {}, item.label), el('small', {}, item.procedure?.label || ''));
}

const linkTodos = (tipo, termo) => ({
  alerts: `/alerts?q=${encodeURIComponent(termo)}`,
  families: `/families?q=${encodeURIComponent(termo)}`,
  hosts: `/hosts?q=${encodeURIComponent(termo)}`,
  host_groups: `/host-groups?q=${encodeURIComponent(termo)}`,
  procedures: `/procedures?q=${encodeURIComponent(termo)}`,
}[tipo] || '/alerts');

document.getElementById('search-form').addEventListener('submit', (evento) => {
  evento.preventDefault();
  const termo = inputBusca.value.trim();
  if (termo) { esconderBusca(); navegar(`/alerts?q=${encodeURIComponent(termo)}`); }
});

document.addEventListener('click', (evento) => {
  if (!evento.target.closest('.topbar')) esconderBusca();
});

addEventListener('keydown', (evento) => {
  if (evento.key === '/' && document.activeElement !== inputBusca) {
    evento.preventDefault(); inputBusca.focus();
  }
  if (evento.key === 'Escape') { esconderBusca(); inputBusca.blur(); }
});

render();
