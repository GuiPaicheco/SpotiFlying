from .lyrics import Lyrics, parse
from .playback import Track

DEMO = [
    (Track("Mapa das Marés", "Lia Horizonte", "Cartas do Céu", 28000), parse("""
[00:00.00]Dobro o céu até encontrar o mapa secreto das marés
[00:04.10]<00:04.10>Deixo <00:04.64>a <00:05.21>luz <00:05.80>atravessar <00:06.80>o <00:07.10>quarto
[00:08.20]A cidade respira do outro lado da janela
[00:12.60]
[00:14.00]Guardamos constelações dentro da mochila
[00:20.00]Quando a rua silencia nasce outro horizonte
[00:24.00]Toda distância cabe numa canção
""", "Demo offline")),
    (Track("Tempo de Vidro", "Vento Norte", "Pequenos Satélites", 21000), parse("""
[00:00.90]O vento escreveu teu nome no vapor
[00:05.00]Cada janela é um céu em miniatura
[00:09.50]Atravesso a noite pelo caminho mais claro
[00:14.80]Ainda guardo aquele sol de janeiro
""", "Demo offline")),
    (Track("Caderno Azul", "Lia Horizonte", "Cartas do Céu", 16000),
     parse("A chuva coleciona instantes.\nAs ruas acendem de dentro para fora.", "Demo offline", False)),
    (Track("Depois do Sinal", "Vento Norte", "Pequenos Satélites", 16000),
     Lyrics("instrumental", source="Demo offline")),
]
