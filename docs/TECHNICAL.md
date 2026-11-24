# Detalhes técnicos

## Arquitetura

SpotiFlying usa Python 3.12, Qt Widgets e PyWinRT. `playback.py` gerencia a sessão de mídia do Windows fora da thread da interface. O seletor usa os identificadores do aplicativo Spotify Desktop. Metadados, estado, linha do tempo e capacidades são normalizados em snapshots. `sync.py` usa relógio monotônico, corrige diferenças de até 250 ms suavemente e reposiciona ao detectar um salto maior ou uma nova faixa.

O parser LRC separa timestamps e quebras visuais. A busca por posição usa bisseção. A renderização mede as palavras com métricas da fonte Qt em coordenadas lógicas. Cada camada tem seu próprio HWND. O modo passivo combina as flags do Qt com estilos Win32 de janela em camadas, transparência de entrada, ausência de ativação e janela de ferramenta. A edição resgata janelas com base na área útil disponível.

O LRCLIB é opcional e usa HTTPS, identificação de cliente, verificação de versão, timeout e cache em memória. Consultas obsoletas são descartadas por geração. A licença MIT do servidor LRCLIB e a disponibilidade da API não transferem direitos sobre letras individuais. Nenhum catálogo, letra comercial ou capa é empacotado. Importação local e demo funcionam sem rede. Consulte a [API LRCLIB](https://lrclib.net/docs.txt) e a [política Spotify](https://developer.spotify.com/policy).

O Spotify Web API fica desabilitado. Volume do Spotify, salvar faixas e abrir um URI específico dependem de capacidades que a sessão local não fornece. Glass usa superfície translúcida sem blur nativo.

## Build Windows x64

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.venv\Scripts\python.exe -m pip_audit -r requirements-lock.txt --no-deps
.\packaging\build.ps1
```

Instale o compilador Inno Setup 6.7.3. Se estiver em pasta personalizada, passe `-Inno caminho\ISCC.exe`. O script executa lint, testes e um smoke no executável. O diretório onedir é a fonte do instalador e do ZIP. O ZIP acrescenta apenas o marcador portátil. O manifesto registra SHA-256. Os binários locais são builds sem assinatura.

Para criar evidências no Windows, execute `SpotiFlying.exe --capture caminho`. O modo abre um fundo ilustrado da própria demo. O smoke do Spotify real usa `SpotiFlying.exe --probe caminho` com uma sessão Desktop em reprodução. O relatório registra presença de metadados e estado, sem título ou artista.

## Matriz de verificação

O ambiente local foi Windows 10 Pro 22H2 x64, build 19045, Intel Core i3-6100T, quatro processadores lógicos e 8 GiB de RAM. O pipeline usa Windows Server 2022 x64.

| Cenário | Evidência |
| --- | --- |
| Parser, matching, catálogo simulado, relógio, configuração e geometria | 12 testes automatizados |
| Demo e janelas | Smoke de transparência, HWND, bandeja, pausa, seek e troca de faixa. Testes com escala Qt 100%, 125% e 150% |
| Spotify Desktop real | Sessão `Spotify.exe` em reprodução com posição, duração e capa recebidas pelo aplicativo compilado |
| Entrada em outro processo | Em um editor Qt independente, três eventos de clique passaram por glifo, área vazia e cartão passivo. Uma rolagem também chegou ao editor |
| Aparência | Capturas do executável com dados fictícios, em fundo escuro e claro, no cartão interativo e na central |
| Matriz física pendente | Windows 11, máquina limpa de cliente, jogo em janela sem bordas, desconexão física de monitor e sessão Spotify sob suspensão ou reconexão |

Para repetir o teste de entrada no desktop interativo, execute `python tests/windows_input_check.py release/clickthrough.json`. Ele abre um editor descartável em outro processo e envia os eventos somente quando o Windows identifica esse processo sob o ponteiro.

### CPU e memória

Medição do processo executado a partir do código-fonte com a demo local. Foram observados 10 segundos por fase, CPU como percentual de um núcleo lógico, e conjunto de trabalho ao final da fase. O comando foi `python tests/windows_performance.py release/performance.json`.

| Fase | CPU média de um núcleo | Memória |
| --- | ---: | ---: |
| Pausado | 0,0% | 80,44 MiB |
| Reproduzindo com sobreposições visíveis | 2,5% | 80,72 MiB |
| Reproduzindo com sobreposições ocultas | 0,0% | 80,95 MiB |

Para o teste de 30 minutos com troca automática de faixa e sobreposições ocultas, execute `python tests/windows_performance.py release/endurance.json --endurance`. O relatório registra o conjunto de trabalho e a contagem de trocas a cada minuto.
