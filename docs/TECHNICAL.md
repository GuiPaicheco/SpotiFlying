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

O ambiente disponível é Windows 10 Pro 22H2 x64, build 19045. Os testes de parser, matching, catálogo simulado, relógio, geometria e configurações rodam com `pytest`. A demo e o provedor local também podem ser exercitados na máquina Windows.

Validações que dependem de hardware ou aplicativos externos devem ser registradas com a máquina, a escala e o método. O smoke automatizado inspeciona a transparência Qt, estilos dos HWNDs e comportamento da demo. O teste entre processos usa um editor Qt independente e registra cliques e rolagem. Ele deve ser executado no desktop interativo. A matriz de validação não atribui os resultados do smoke ao Windows Sandbox, Windows 11, ambientes de jogo ou monitores que não foram exercitados.
