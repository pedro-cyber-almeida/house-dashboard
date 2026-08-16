# AGENTS.md — Dashboard da casa

Registo de progresso para sobreviver a compactações de contexto. Respostas em
português europeu.

## Regras não negociáveis

- **Autenticação intocada** (`src/dashboard/auth/`): passlib+bcrypt, cookies de
  sessão assinados do Starlette (`SessionMiddleware` em `main.py`).
- **Base de dados: só migrações aditivas** (novas colunas/tabelas
  não-nulas com default ou nulas; nunca recriar/remover dados existentes).
- **Segurança do upload de logótipos intocada** (`api/admin/logo.py`):
  validação por bytes mágicos no servidor, 512 KB, sanitização SVG; os ícones
  exibem-se SEMPRE em `<img src="data:...">`, nunca em `innerHTML`.
- `models.py` **não pode** ter `from __future__ import annotations` (o
  metaclass do SQLModel precisa das anotações avaliadas).
- Segredos só no `.env` (fora do git); `DASH_COOKIE_SECURE="true"` vive no
  `docker-compose.yml`.

## Stack / runtime

- Python 3.13 (uv), FastAPI + SQLModel/SQLite, uvicorn, `python:3.13-slim` em
  Docker com user não-root `dashboard`, volume `dashboard_data:/data`
  (BD + `.secret`).
- Frontend vanilla (sem frameworks): `static/js/{app,admin,api}.js`,
  `static/css/style.css`, tokens dark/light em custom properties.
- Checks: `uv run ruff check .` + `ruff format --check .`; JS com
  `node --check` (copiar para `.mjs`).
- **Nota**: `models.py`/`seed.py` usam `from sqlmodel import select` (o
  `sqlalchemy.select` faz o `Session.exec` devolver `Row` no sqlmodel 0.0.39).
- O cookie de sessão chama-se **`dashboard_session`** (ver `main.py`), tem
  `Secure` (compose). httpx/PowerShell não o reenviam sobre http (o browser
  em localhost aceita) — em testes com httpx, extrair o valor do header
  `set-cookie` (prefixo `dashboard_session=`) e repassar à mão em `Cookie`;
  para teste rápido pode criar um admin temporário na BD e removê-lo ao fim.

## Fases de trabalho

### Fase 1 — Verificação de estado real no servidor: ✅ concluída e testada

- **Decisões aprovadas**: estado `degraded` como 4.º valor (âmbar); cache TTL
  30 s por URL; timeout 3 s; concorrência máxima 5; paths de saúde em ordem
  `/health /healthz /ping /api/health /api/ping /`; `httpx` declarado como
  dependência direta (`pyproject.toml`) com **cliente dedicado** ao probe —
  `verify=False` isolado aí, nunca partilhado com outro código.
- **Ficheiros alterados**:
  - `pyproject.toml` — `httpx>=0.28.1`
  - `config.py` — `probe_timeout`/`probe_cache_ttl` (env
    `DASH_PROBE_TIMEOUT`, `DASH_PROBE_CACHE_TTL`)
  - `schemas.py` — `ServiceStatusRead` ganhou `online: str` (4 valores) e
    `checked_at: datetime | None`
  - `api/services.py` — probe por paths de saúde + cache com double-check +
    semáforo de concorrência; endpoint `GET /api/services/assigned` mantido
    (mesmo contrato, agora com `checked_at`)
  - `static/js/app.js` — `LED_META.degraded` (âmbar), resumo com
    `${n} degradados` e tooltip com a hora da verificação
  - `static/css/style.css` — `.led-degraded`
- **Testado** (2026-08-16, no container, `phase1_e2e.py`): handlers efémeros
  por porta com classes separadas → 200 em `/health` = `online`; sempre 503
  = `degraded`; porta morta = `offline`; nome inexistente = `unknown`
  (`checked_at` nula). 2.ª chamada no TTL devolve o mesmo `checked_at` em
  ~0 s (cache). Cleanup feito: serviços de teste e conta `testbot` removidos.

### Correção de deploy — porta publicada configurável: ✅ concluída

- `docker-compose.yml` lê `${DASH_BIND:-127.0.0.1:8090}:8000`; o valor real
  vem do `.env` (variável `DASH_BIND`, documentada no `.env.example`):
  - `DASH_BIND=127.0.0.1:8090` (produção, atrás do reverse proxy)
  - `DASH_BIND=127.0.0.1:8000` (dev no browser)
- Um `.env` desta cópia portava sem `DASH_BIND`: adicionado
  `DASH_BIND=127.0.0.1:8090` (ficheiro UTF-8 sem BOM — anexar com
  `[System.IO.File]::AppendAllText`, nunca `Set-Content`).
- **Nota de operação**: o upstream do reverse proxy tem de apontar para a
  porta escolhida; o bind antigo era `0.0.0.0:8000`, agora
  `127.0.0.1:8090` (só loopback).

### Fase 2 — Organização visual: ✅ concluída e testada (API + render no browser)

- **Decisões aprovadas** (revisadas antes do código):
  - `categoria` = **texto livre** colado no serviço (sem tabela `categories`):
    `services.categoria VARCHAR(64) NULL`, índice `ix_services_categoria`.
  - Ordem por utilizador = coluna na ligação: `user_services.ordem INT NULL`
    (não há tabela dedicada; a ordem só existe para serviços atribuídos).
  - **Admin sem ordem pessoal** (vê o catálogo por nome). *(guest removido em 2026-08-16)*
  - **Gesto de reordenação (mudado a 2026-08-16, pedido do user)**: o
    drag-and-drop foi **abandonado** (não funcionava visualmente no browser)
    e substituído por **botões ↑/↓ por tile**: visíveis no hover, sempre
    visíveis em touch (`@media (hover: none)`); cada clique troca o tile com o
    vizinho **da mesma categoria** e chama o mesmo `PUT /api/services/order`
    com a lista completa; o 1.º da categoria não tem ↑ e o último não tem ↓.
    Sem toasts por clique (o movimento é o feedback); toast só em erro.
    Flag `reorderBusy` bloqueia cliques em concurrently durante o PUT.
  - `PUT /api/services/order`: transação única (1 `commit` no fim), e a lista
    rejeitada com **400** se não corresponder ao conjunto exato dos serviços
    atribuídos (falta, extra, ou duplicados) — pedido explícito do user.
- **Ficheiros alterados**:
  - `models.py` — `Service.categoria`, `UserServices.ordem`
  - `database.py` — `_ensure_columns()`: `PRAGMA table_info` +
    `ALTER TABLE … ADD COLUMN` + `CREATE INDEX IF NOT EXISTS`
    (create_all não retoca tabelas existentes)
  - `schemas.py` — `categoria` em `ServiceRead/Create/Update`;
    `ordem` em `ServiceStatusRead`; novo `ServiceOrderIn`
  - `api/admin/services.py` — criar/editar serviços com `categoria`
    (strip; vazio → `None`)
  - `api/services.py` — `_assigned` volta `(services, ordem_map)`; user ordena
    por `(ordem NULL→fim, ordem, nome)`; novo `PUT /order`; endpoint mantém
    contrato (ganhou `categoria` + `ordem` no payload)
  - `static/js/app.js` — agrupamento (`Sem categoria` em último), pesquisa
    instantânea (nome+descrição, case/diacritics, **Escape limpa**),
    botões ↑/↓ por tile com `moveInCategory(svc, alvo)` (troca na lista flat +
    PUT completo); todos os códigos de drag (pointer events, ghost, slot,
    alça) removidos
  - `static/js/admin.js` — campo "Categoria" no formulário (com
    `datalist` das categorias em uso) + tag no cartão de serviço
  - `static/css/style.css` — `.groups`, `.group-title`, `.search`,
    `.tile-wrap`, `.tile-nav`, `.tile-btn`, `.cat-tag` (`.drag-handle`,
    `.tile-slot`, `.tile-ghost` removidos com o drag)
  - `docker-compose.yml` / `.env.example` — ver correção de deploy acima
- **Testado** (2026-08-16, `phase2_e2e.py` no container, 36/36): schema novo
  na BD real (cols + índice); categoria create/patch/limpar; ordem inicial
  por nome; PUT ordem completa → GET devolve a nova com `ordem` 0..n-1;
  400 em lista incompleta / id alheio / duplicados / **como admin**; ordem
  intacta após rejeições; **isolamento por utilizador** (user2 tem a sua
  ordem, user1 mantém a dele). Limpeza total (serviços `pz-*`, contas
  temporárias, sem `ordem` órfãs).
- **Bug de render encontrado e corrigido no browser** (2026-08-16,
  agent-browser contra `127.0.0.1:8090`): o header mostrava "4/4 online"
  mas a grelha estava vazia, sem erro na consola, serviços com
  `categoria=null`. Sintoma = `#view` só continha `DIV.page-head`;
  `.groups` nunca chegava ao DOM. **Causa raiz**: em `loadDashboard`
  (`app.js`) o `groupsEl` era criado mas **nunca anexado ao `els.view`** —
  o `els.view.append(...)` só levava a `page-head`, e o
  `renderGroups()` punha os tiles num nó desanexado. Os dados estavam íntegros:
  o balde "Sem categoria" funcionava, termo de pesquisa vazio não
  filtrava nada, e contador + grelha viam o mesmo array. **Correção**:
  acrescentar `groupsEl` como 2.º argumento de `els.view.append(...)`
  (mesma chamada que anexam a `page-head`). **Validado** pós-rebuild:
  login `pvviewer` (user, 4 serviços) → grupo "SEM CATEGORIA 4" com os
  4 tiles; pesquisa "jarrad" → "Nenhum serviço encontrado";
  `Escape` → repesca os 4. Conta temporária `pvviewer` removida.
- **Substituição drag→botões (2026-08-16)**: o drag-and-drop mostrou-se
  instável visualmente no browser real (tiles sem reordenar, alça a
  desaparecer, 1.º tile a sumir ao arrastar o último). Por decisão do user,
  o drag foi **removido por inteiro** (pointer events, ghost, slot, alça —
  código e CSS) e substituído por botões subir/descer, que reutilizam o
  endpoint `PUT /order` já coberto a 36/36.
- **Ferramentas do ambiente (2026-08-16)**: o `agent-browser` **falha a
  lançar no Windows deste user** — o user é os "olhos" no browser; eu faço o
  código + o rebuild e dou instruções passo a passo. Nota: em 2026-08-16
  houve uma sessão em que o ficheiro `app.js` ficou por um fio com parêntesis
  desequilibrados entre iterações de depuração; depois de cada série de
  edições em `app.js`, correr SEMPRE `node --check` (copy para `.mjs`).
- **Validação manual (o user é os olhos): ✅ validada (2026-08-16)** — os
  botões ↑/↓ funcionaram no browser. Conta `dndtest` **removida** e todas as
  linhas `user_services.ordem` puestas a `NULL` na BD.
- **Mudança de estado do tile (2026-08-16, pedido user)**: a `tile-dot` saiu
  da linha principal (sobrepunha-se aos botões no hover) e virou câpsula
  inline na 2.ª linha — `.tile-status` = ponto + etiqueta de texto
  (`online`/`offline`/`degradado`/`desconhecido`; `led.label` em
  `LED_META`), tooltip com a descrição completa; o `.tile` ganhou
  `padding-right: 34px` para o texto não ir por baixo dos botões.
- **Remoção do modo guest + variável Jellyfin (2026-08-16, pedido user)**:
  - Papéis: só `admin` e `user` (`Role` Literal em `schemas.py`; `ROLES` em
    `admin.js`; guards em `me.py`; branch guest em `_assigned`/`/order` em
    `services.py`; refs em `app.js`); migr. de dados aditiva em
    `database.py`: `UPDATE users SET role='user' WHERE role NOT IN
    ('admin','user')`.
  - `DASH_JELLYFIN_URL` fora de `config.py`/`.env.example`; seed sem criação
    do serviço Jellyfin (só bootstrap do 1.º admin). O catálogo (incluindo
    "Jellyfin") é agora gerido só pela ecrã admin; serviços futuros que ainda
    não existem funcionam já: o probe devolve `unknown`/`offline` até
    existirem (sem código novo).
  - `README.md` escrito (EN, para publicação futura no GitHub/Docker Hub):
    quickstart Docker, tabela env, estados de saúde, dev local, layout.
  - **Plano de publicação (decisão user, em curso)**: o user vai publicar a
    imagem no GitHub + Docker Hub mais para a frente; "qualquer pessoa mete o
    nome da imagem e implementa". Quando chegar lá: tag da imagem,
    nome no Docker Hub; LICENSE (MIT, "2026 house-dashboard contributors") e
    README (EN) já exist.
- **Ronda i18n/nome/categorias/icones (2026-08-16, pedido user)**:
  - **App toda em inglês**: strings de PT removidos de `app.js`, `admin.js`,
    `api.js`, `index.html` (lang="en"), `style.css` (comentários) e de TODOS
    os `detail=`/logs em Python (auth, deps, me, services, admin/*, logo,
    seed).
  - **Nome "casa" customizável**: `DASH_APP_NAME` (default
    "House Dashboard") em `config.py`; novo endpoint **público**
    `GET /api/brand` em `main.py`; `app.js::loadBrand()` pinta
    `document.title` + nós `[data-brand]` (topbar e login). No `.env.example`.
  - **Categorias auto-sugeridas**: `admin.js` tem `CATEGORY_HINTS`
    (name→Media/Home automation/Network/AI/Security/Files & cloud/Devops/
    Chat/Finance) — preenche a categoria no formulário **só em criações novas
    e enquanto o campo não foi tocado** (`categoriaTouched`); input manual
    ganha sempre. Dashboard já ordenava grupos A-Z com "No category" ao fim.
  - **Logos automáticos**: novo endpoint admin
    `POST /api/services/{id}/fetch-icon` (em `api/admin/logo.py`): varre
    `<link rel*=icon>` na home + fallback `/favicon.ico`, valida bytes
    mágicos (PNG/JPEG/SVG, 512 KB, SVG sanitize — MESMAS regras do upload) e
    grava o data-URI em `icone`. Botão "Fetch icon" no card de serviço da
    admin. Limites honestos: serve estar online; .ico/.webp não aceites
    (por paridade com o upload).
  - **Testes desta ronda**: ruff check+format OK; node --check (app/admin)
    OK; container healthy; `/api/brand` 200; JS servido sem acentos PT.
- **Ronda renames cols PT→EN + redesign (2026-08-16, pedido user)**:
  - **Nomes das colunas (e chaves da API) em inglês**: `nome`→`name`,
    `icone`→`icon`, `descricao`→`description`, `categoria`→`category`,
    `ordem`→`position`, `ativo`→`active`. Afecta `models.py`, `schemas.py`,
    `api/services.py`, `api/admin/{services,users,logo}.py`, `auth/{routes,deps}.py`
    (só a ref `user.active`, lógica intacta), `seed.py` (e o leftover
    `display_name="Administrator"`), `app.js`, `admin.js` (vars DOM locais
    `nome/descricao/categoria` → `nameIn/descIn/catIn`; datalist
    `svc-categorias`→`svc-categories`; payloads com chaves EN). Leftover PT
    do message `{"message": "Ordem guardada."}` → "Order saved."
    (api/services.py).
  - **Migração em `database.py::_ensure_columns`** (idempotente, 3 passos):
    (1) ADD COLUMN dos nomes originais PT p/ BDs pré-Fase 2; (2) renames
    PT→EN via `ALTER TABLE … RENAME COLUMN`, só se a col antiga existe E a
    nova não; (3) `DROP INDEX ix_services_categoria` +
    `CREATE INDEX ix_services_category` + o UPDATE de role legado. Testado
    em BD descartável no container: o SQLite 3 atualiza as refs dos índices
    no `sqlite_master` automaticamente (unique index de `name` intacto,
    `integrity_check` ok). **Aplicado à BD real com sucesso**: as 3 tabelas
    têm as cols EN, 0 refs PT, 10 serviços + categorias/ícones intactos.
  - **Redesign (estética)**: tema light refeito p/ contraste real —
    página `#e8ecf3` (os cards brancos destacam), campos `#f6f8fc` (nada de
    branco sobre branco), `--muted #4c5a6e`, accent `#1f5cc9` (WCAG ok),
    sombras em 2 camadas. Glow radial subtil no topo (`--glow`, fixed) nos
    2 temas. Fixes: `.avatar-preview` tinha `color:#fff` sobre
    surface-2 (branco sobre branco em light) → `var(--text)`; o span da
    `chip-avatar` no login/topbar agora preenche o círculo
    (`width/height 100%`, grid, fundo hsl) em vez de texto branco solto.
  - **Smoke test (no container, `zzsmoke` admin temporário, removido ao fim)**:
    login 200; `/api/me` devolve `active`; `/api/services/assigned` devolve
    `name/description/icon/category/position` e probe funcional. **Nota p/
    o futuro**: o cookie de sessão chama-se **`dashboard_session`**
    (não `session`) — em httpx no container, passar o header `Cookie`
    extraído do `set-cookie` (cookie `secure` sobre http).
- **Restrições conhecidas**: reordenação só **dentro da mesma categoria**
  (a categoria é do serviço, não do utilizador); botões escondidos durante a
  pesquisa (a lista visível seria um subconjunto e a API exige o conjunto
  exato); a ordem aplica-se apenas à conta `user` (admin sem botões).

### Fase 3 — PWA: ✅ concluída e testada (2026-08-16, tarde)

- **Manifest dinâmico**: `GET /manifest.json` em `main.py` (não é ficheiro
  estático) — `name`/`short_name` vêm de `DASH_APP_NAME`, `display:
  standalone`, `theme/background #0f1218`, ícones 192/512 (o 512 com
  `purpose: any maskable`). Coberto pela CSP `default-src 'self'`.
- **Service worker** `static/sw.js`: *network-first* com fallback em cache
  (`house-dashboard-shell-v1`); **ignora sempre `/api/`** (probes e estado
  são sempre ao vivo; offline mostra o shell com o último visualiado).
  Precache: `/`, css, os 3 js, favicon, ícones. Registo em `app.js` **só em
  contexto seguro** (https ou localhost), falhas ignoradas — a app funciona
  sem o SW.
- **Ícones gerados por script de stdlib**: `scripts/make_pwa_icons.py`
  (struct + zlib, sem PIL) desenha o LED da marca →
  `static/icons/icon-{192,512}.png`. Regenerar: `uv run python
  scripts/make_pwa_icons.py`. `static/favicon.svg` (LED) ligado via
  `rel="icon"` no `index.html` (+`theme-color` dark, `description`,
  `apple-touch-icon`, `manifest`).
- **Testada** (container, `smoke_pwa.py`, 18/18): 200 + content-type
  corretos em todos os recursos PWA; manifest JSON válido com os campos
  necessários; PNGs válidos 192×192/512×512 (assinatura + dimensões);
  registo do SW presente em `app.js`; ruff + node --check ok; container
  healthy.
- **Por validar (browser)**: instalação "Add to home screen"/ecrã inicial e
  o fallback offline visual — o resto está provado por smoke.

## Notas de ambiente

- Dev: `fastapi dev` crasha no Windows (emoji/encoding) — usar `uvicorn` ou
  Docker.
- `docker compose up -d --build` é o fluxo de rebuild; os estáticos e o
  wheel são embutidos na imagem, o estado em `dashboard_data`.
- A partir de 2026-08-16 o ecrã vive em **`http://localhost:8090`**
  (default de `DASH_BIND`; antes era `0.0.0.0:8000`). Em dev local, mudar a
  variável no `.env` para `127.0.0.1:8000`.
- Serviços da casa na BD (estado 16/08 à tarde, col. `name`): Jellyfin,
  Jellyseerr, Home Assistant, JARVIS, Radarr, Sonarr, Prowlarr, Bazarr,
  qBittorrent, Speedtest — categorias `Media`/`Infrastructure`/`AI` (o user
  vai redefinir o catálogo). Descrições em UTF-8 — inserir sempre via script
  em `docker cp` + execução no container, nunca via pipe do PowerShell.
- **Compaction (pedido user 2026-08-16)**: `~/.config/opencode/opencode.json`
  tem `"compaction": { "auto": true, "reserved": 16000 }` — compactação
  automática quando falta ~16k tokens de janela. Nota: `/compact` (e
  `/undo`, `/redo`) são comandos do TUI — o agente **não os invocam por
  ferramenta**; a config acima é o mecanismo automático.
- **Publicação (estado 2026-08-16)**: repo git local com commit inicial
  (identidade inline `pedro <pedro@localhost>` — não havia identidade git
  global; o user pode `git commit --amend --reset-author` se quiser outra).
  CI: `.github/workflows/image.yml` faz build + push de
  `ghcr.io/<owner>///<repo>` em tag `v*` — requer pacote GitHub **criado**
  (Settings → Packages) com *Public* + permission `packages: write` declarada
  no workflow. **Conta/nome Docker Hub por definir pelo user**: job
  comentado no workflow à espera dos secrets `DOCKERHUB_USERNAME` e
  `DOCKERHUB_TOKEN`. Push remoto e tags ainda por fazer pelo user
  (não há remote configurado nesta cópia).
