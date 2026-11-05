# ADR 0005 — Operação do sistema no ginásio: local + sync, sem cloud no caminho crítico

**Data:** 2026-05-26 · **Adenda macOS:** 2026-09-07
**Estado:** Aceite (plataforma revista — ver adenda no fim)
**Relaciona-se com:** [ADR 0001](0001-bd-acumuladora-de-snapshots.md), [ADR 0004](0004-baseline-e-cobertura-temporal.md)

## Contexto

O sistema (pipeline + BD + dashboard) corre na máquina da gerente, no ginásio. gerente opera tudo de A a Z; André intervém pontualmente quando algo parte. A BD acumulada é o único asset insubstituível — se a máquina morre, perdemos história.

Três decisões operacionais críticas pediam fixação:

1. **Como protegemos a BD** (única cópia local).
2. **Como entra André na máquina dela** para debug.
3. **Como Python corre** lá dentro.

Considerámos para cada uma várias opções, com os trade-offs explorados em conversa de 2026-05-26.

## Decisão

### 1. Backup: BD local + sync de cópias datadas via OneDrive corporativo

**Anti-padrão rejeitado:** colocar o ficheiro `ginasio.sqlite` dentro de uma pasta sincronizada. A cliente de sync (OneDrive ou Drive) tenta copiar o ficheiro enquanto o app o tem aberto — corrupção e ficheiros em conflito (`base-DESKTOP-001.sqlite`) é o cenário esperado, não o excecional.

**Padrão adoptado:** BD viva em pasta local *não sincronizada*. Após cada ingestão bem-sucedida, o app faz uma cópia atómica datada para uma pasta sincronizada no OneDrive corporativo do ginásio.

```
C:/gym-analytics-dashboard/data/ginasio.sqlite          ← BD viva, não sincronizada
OneDrive/gym-analytics-dashboard-Backups/
  base-2026-05-26_143215.sqlite             ← snapshot pós-ingestão
  base-2026-05-27_091042.sqlite
  ...
OneDrive/gym-analytics-dashboard-Raw/
  2026-05-13_pagamentos.csv                  ← CSVs originais
  2026-05-13_acessos.xlsx
  ...
```

**Mecânica:**
- Cópia da BD: `VACUUM INTO 'OneDrive/.../base-YYYY-MM-DD_HHMMSS.sqlite'` — comando nativo SQLite, atómico, seguro com ficheiro vivo.
- Política de retenção: últimos 30 dias diários + 1 por mês para o histórico antigo. App apaga os mais antigos automaticamente.
- CSVs originais entram numa pasta separada sincronizada — são o fallback último (re-ingestão completa) se a BD se perder.

**Conta cloud:** OneDrive corporativo do ginásio, com André como contributor com permissão de leitura. Decisão consciente: conta corporativa (não pessoal da gerente) garante que a propriedade dos dados fica com o ginásio quando houver rotação de pessoal.

**Recuperação em caso de perda da máquina:** instalar Python noutro PC, copiar o último backup do OneDrive, voltar a operar em ~30 minutos. Zero perda de dados.

### 2. Acesso remoto: AnyDesk ad-hoc

a gerente abre o AnyDesk quando precisa de ajuda e partilha o ID com André. Sessão termina quando ele desliga. Sem acesso permanente, sem VPN, sem credenciais a guardar.

Vantagem: zero superfície de ataque permanente, modelo mental simples para a gerente ("quando o André precisar, eu abro").

Quando isto deixar de chegar (ex: piloto bem-sucedido + crescimento + manutenção mais frequente), reabrir esta decisão a favor de algo mais robusto (Tailscale, RDP via VPN). Por agora é suficiente.

### 3. Python: venv local sobre Python instalado normalmente

Instalação manual de Python 3.x na máquina dela, `python -m venv .venv`, `pip install -r requirements.txt`. Um atalho no desktop executa `streamlit run src/dashboard.py`.

Rejeitado:
- **Pyinstaller**: produz binário monolítico mas opaco para debugar; cada update de dependência exige recompilação. Útil quando o app vai para muitos utilizadores externos — não é o nosso caso.
- **Docker Desktop em Windows**: pesado, frágil, exige licenciamento corporativo da Docker em ambientes profissionais.
- **Cloud (Streamlit Cloud / Render)**: inverte a decisão anterior (sistema no ginásio). Não é descartado para o futuro — é onde podemos migrar se o piloto local correr bem e quiser escalar a múltiplos ginásios.

## Consequências

**Ganhos:**
- **gerente é dona da operação.** Tudo corre no ginásio; não depende de internet para usar o dashboard (apenas para sincronizar backups, e mesmo isso é assíncrono e tolerante a falhas).
- **Backup robusto sem fricção.** gerente não tem de pensar em backups; acontecem ao ritmo dos uploads.
- **Setup conhecido por André.** Python + venv é o caminho que ele domina; debug remoto via AnyDesk é o mais simples que existe.

**Custos:**
- **Setup inicial presencial.** Instalar Python na máquina da gerente, configurar OneDrive sync, instalar AnyDesk — uma manhã de trabalho presencial (ou via partilha de ecrã guiada).
- **Dependência da conta corporativa do ginásio.** Se a senha mudar ou a conta for desactivada, perdemos sync. Mitigado por documentar credenciais num gestor seguro e ter cópia local da BD que sobrevive a problemas de cloud.
- **gerente usa o PC para outras coisas.** Risco de fechar acidentalmente o terminal/Streamlit. Mitigado por atalho no desktop e ícone visível na bandeja.

## Setup inicial — checklist (para a fase 5 da execução)

1. Confirmar conta OneDrive corporativa do ginásio; André adicionado.
2. Instalar Python 3.11+ na máquina da gerente.
3. Criar `C:/gym-analytics-dashboard/`, clonar / copiar o repositório.
4. `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`.
5. Criar pastas `OneDrive/gym-analytics-dashboard-Backups/` e `OneDrive/gym-analytics-dashboard-Raw/`. Configurar sync seletivo.
6. Atalho no desktop: `streamlit run src/dashboard.py`.
7. Instalar AnyDesk; partilhar ID com André.
8. Sessão presencial inicial com gerente — ela faz o primeiro upload guiado.

## Quando reabrir esta decisão

- Se aparecer um segundo ginásio (escalar para multi-tenant): provavelmente faz sentido migrar para cloud.
- Se a máquina da gerente for unstable / partilhada com outros usos críticos: avaliar dedicar uma mini-máquina (NUC ou similar) só para o dashboard.
- Se AnyDesk ad-hoc deixar de chegar pela frequência de manutenção: passar a Tailscale/RDP.


---

# Adenda — a máquina da gerente é um Mac (2026-09-07)

Esta ADR foi escrita a assumir Windows: `C:/gym-analytics-dashboard/`, `.venv\Scripts\pip`,
atalho no desktop, "Docker Desktop em Windows" entre as opções rejeitadas.
Confirmou-se que a máquina é **macOS**.

**As quatro decisões mantêm-se**: BD local não sincronizada, backups datados para
uma pasta sincronizada, AnyDesk ad-hoc, venv sobre Python instalado normalmente.
Nenhuma delas dependia do sistema operativo. Muda a mecânica.

**O código não precisa de alterações.** Todos os caminhos são construídos com
`pathlib` ancorado em `__file__` (`src/db.py`, `src/ingestion.py`), e não há uma
única chamada específica de Windows no `src/`. Verificado a 07-09-2026.

## O que muda

| | Windows | macOS |
|---|---|---|
| Pasta do projecto | `C:/gym-analytics-dashboard/` | `~/gym-analytics-dashboard/` — **ver aviso do iCloud** |
| Interpretador do venv | `.venv\Scripts\python.exe` | `.venv/bin/python` |
| Lançador | `abrir-painel.bat` | `abrir-painel.command` (duplo clique no Finder) |
| Pasta do OneDrive | `OneDrive/...` | `~/Library/CloudStorage/OneDrive-<Org>/...` |

## ⚠️ O iCloud é a armadilha desta plataforma

O anti-padrão desta ADR — nunca pôr a BD viva numa pasta sincronizada — é **mais
fácil de violar por acidente no macOS do que no Windows**. O macOS oferece
"Pastas Secretária e Documentos" no iCloud Drive, e em muitas máquinas isso está
ligado. Instalar o projecto em `~/Documents/gym-analytics-dashboard` põe o `ginasio.sqlite`
dentro do iCloud sem ninguém decidir nada, e reproduz exactamente a corrupção
que esta ADR existe para evitar.

**Regra:** instalar em `~/gym-analytics-dashboard/` (raiz da pasta pessoal, que o iCloud
não sincroniza). Antes de instalar, confirmar em *Definições do Sistema →
[nome] → iCloud → iCloud Drive → Pastas Secretária e Documentos*.

## Python no macOS

O macOS traz um Python 3 próprio, mas é da Apple, é antigo e não deve ser usado.
As dependências exigem **3.11 ou superior** (pandas 3.0 e numpy 2.x).

Instalar pelo **instalador oficial de python.org** (`.pkg` com interface gráfica),
não por Homebrew: o Homebrew exige as Command Line Tools do Xcode e trabalho no
terminal, e esta é uma máquina de trabalho de alguém que não é técnico. O
instalador oficial deixa `python3` disponível e acabou.

## O lançador

`abrir-painel.command` faz o mesmo que o `.bat`: verifica o venv, espera que o
`/_stcore/health` responda, abre o browser e só então cede o terminal ao
Streamlit. Duas condições para funcionar ao duplo clique:

- **Bit de execução.** Guardado no git (`100755`). Se se perder, repor com
  `chmod +x abrir-painel.command`.
- **Fins de linha LF.** Com CRLF o shebang fica `/bin/bash\r` e o macOS
  responde "bad interpreter". Garantido por `.gitattributes` (`*.command text eol=lf`).

Se os ficheiros forem transferidos como `.zip` descarregado em vez de por `git
clone`, o Gatekeeper marca-os em quarentena e o duplo clique é bloqueado na
primeira vez. Resolve-se com *clique direito → Abrir* uma vez, ou
`xattr -d com.apple.quarantine abrir-painel.command`.

## AnyDesk no macOS

Precisa de permissões que o Windows não pede, concedidas à mão em *Definições do
Sistema → Privacidade e Segurança*: **Gravação do Ecrã** e **Acessibilidade**.
Exigem palavra-passe de administrador e **reiniciar o AnyDesk** depois de
concedidas. Sem isto a sessão liga mas mostra um ecrã preto — sintoma que não
sugere a causa. Fazer isto na sessão presencial de instalação, não a meio de uma
avaria.

## Checklist de instalação (substitui a da secção anterior)

> **Versão operacional, testada num Mac a 18-10-2026:**
> o guia de instalação (só no repositório privado). Acrescenta
> o que o ensaio ensinou: clone com `--filter=blob:none --sparse` (só `src/` e
> `data/` chegam ao Mac), Python 3.14 e não 3.15, as Command Line Tools que o
> `git` pede, o token do GitHub, e os dados por LocalSend. A lista abaixo fica
> como resumo.

1. Confirmar que "Pastas Secretária e Documentos" do iCloud **não** abrange onde
   o projecto vai ficar.
2. Instalar Python 3.11+ pelo instalador de python.org.
3. `git clone` (ou cópia) para `~/gym-analytics-dashboard/`.
4. `cd ~/gym-analytics-dashboard && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
5. `chmod +x abrir-painel.command` (se não vier já executável).
6. Duplo clique no `abrir-painel.command` para confirmar que arranca e abre o browser.
7. Arrastar o `abrir-painel.command` para a Dock, para ficar à mão.
8. Criar as pastas de backup no OneDrive corporativo e configurar a sincronização.
9. Instalar o AnyDesk e conceder Gravação do Ecrã + Acessibilidade.
10. Sessão com a gerente — primeiro carregamento guiado por ela.

## Por verificar antes da instalação

- **Que versão do macOS e que chip** (Apple Silicon ou Intel). Há rodas
  compiladas para os dois, mas convém saber antes.
- **Se a conta dela é de administrador** — é preciso para instalar o Python e
  para conceder as permissões ao AnyDesk.

---

## Adenda — ingestão por pasta e backup automático (2026-09-07)

A ADR desenhava a operação assumindo que alguém correria a ingestão. Não vai
haver ninguém: a gerente não usa linha de comandos e o painel não tinha por
onde receber um ficheiro.

**A extração passa a entrar por pasta.** Larga-se o `.xlsx` em `data/entrada/`
e o resto acontece sozinho — no lançador, ao arrancar, e no painel, à
interação seguinte. `src/entrada.py` reconhece o relatório pelas colunas, tira
a data do snapshot do conteúdo (o último dia coberto) e arruma o ficheiro em
`data/snapshots/` com o nome da convenção. O nome com que o ficheiro chega é
irrelevante, o que interessa porque o software de gestão não o controla.

**Ficou preferido à alternativa óbvia** — um `st.file_uploader` no painel —
por duas razões. O upload obriga a navegar até ao ficheiro dentro do browser,
que é mais passos do que arrastar; e um ficheiro que entre pelo browser não
fica em lado nenhum se a ingestão falhar, enquanto o que é largado na pasta
está sempre algures. Um botão continua a poder ser acrescentado por cima
disto: chamaria a mesma função.

**O que corre mal sai da pasta e explica-se.** Vai para
`data/entrada/com problemas/` com um `.txt` ao lado em português corrido —
sair da caixa de entrada é essencial, senão o mesmo ficheiro voltava a falhar
a cada arranque. As duas recusas prováveis já se verificaram contra os
ficheiros reais: o relatório errado de 05-08 é rejeitado a nomear as colunas
em falta, e um ficheiro repetido é apanhado pelo hash antes sequer de ser
aberto.

**O `VACUUM INTO` desta ADR está implementado** (`entrada.copia_de_seguranca`),
e corre antes de cada ingestão — que é agora o único momento em que a base
muda. Uma cópia por dia, seis guardadas, ao lado da BD. Falta a metade
sincronizada: as cópias ficam na máquina, não no OneDrive. Para uma avaria de
disco isso não chega, e é o que resta fechar aqui.

---

## Adenda — a metade sincronizada (2026-10-19)

Fechada. Depois de cada ingestão, `entrada.copia_para_a_nuvem` guarda uma
cópia da base na pasta indicada em `GINASIO_COPIAS_NUVEM` (no Mac da gerente, o
iCloud Drive), seis guardadas. Três decisões:

- **A cópia da nuvem é a de depois da ingestão; a local continua a ser a de
  antes.** Servem para coisas diferentes: a local desfaz uma ingestão má, a da
  nuvem sobrevive ao disco. Se a da nuvem fosse a de antes, a extração mais
  recente nunca estava protegida.
- **A base viva continua fora da pasta sincronizada**, como esta ADR exige. O
  `VACUUM INTO` escreve num temporário local; para a nuvem só vai o ficheiro
  acabado, com troca de nome no fim.
- **Não cria a pasta-mãe.** Com o iCloud desligado, criar o caminho à mão dava
  uma pasta que parece sincronizada e não é. Em vez disso a ingestão conta
  como feita e aparece um aviso; a barra lateral do painel mostra sempre a
  data da última cópia.

Ficou de fora copiar também os `.xlsx` originais: a base depois da ingestão já
os contém, e os originais continuam em `data/snapshots/`.

---

## Adenda — instalação real sem git (Outubro de 2026)

No Mac da gerente o git não ficou instalado: vem com as Command Line Tools, e o
instalador pediu 20 GB livres que o disco não tinha (causa por confirmar — as
Command Line Tools costumam ser poucos GB; 20 GB é a ordem do Xcode). A
decisão 3 (venv sobre Python instalado normalmente) mantém-se, e o **git
continua a ser o caminho preferido** — dá a versão instalada a qualquer
momento, atualizações só do que mudou e regresso a versões anteriores. Para
quando não for possível:

- **Plano B: um `.zip` só do código**, gerado com `git archive` a partir do
  `main` (`src/`, o lançador, `requirements.txt` e a pasta de entrada vazia).
  Preserva a permissão de execução do lançador e grava o commit de origem no
  próprio ficheiro. Nunca leva dados nem `.env`.
- **Nunca copiar a pasta inteira do projeto.** Foi o que se fez no dia, e
  levou o `.git`, o material de apresentação e o `.env` da máquina de origem
  — que pode apontar para a base de demonstração. O lançador passou a recusar
  processar a pasta de entrada nesse caso (`dba69ad`), e no Mac da gerente o
  painel recusa abrir com a base de demonstração (`29aa2f9`: o
  `abrir-painel.command` define `GINASIO_PRODUCAO=1`).
- **Arrumar a instalação copiada** faz-se com um clone limpo ao lado, levando
  só a base real e os snapshots, e um `.env` escrito de novo — nunca o
  copiado. A pasta antiga muda de nome e só se apaga uma semana depois.

Passo a passo em o guia de instalação (só no repositório privado).
