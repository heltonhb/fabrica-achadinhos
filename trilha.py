"""
trilha.py — Trilha sintetizada leve (numpy), sem depender de banco de música.

Bed de fundo para achadinhos: batida pop leve (kick + hat) e acordes
dedilhados (Karplus-Strong) na progressão C-G-Am-F. Pico normalizado a 0.5;
no mix final entra com BGM_VOLUME (ducking sob a locução).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

SR = 44100
BPM = 100.0
BEAT = 60.0 / BPM          # 0.6s
PICO = 0.5                 # pico de normalização do bed (padrão validado)


def _pluck(freq: float, dur: float, decay: float = 0.996) -> np.ndarray:
    """Corda dedilhada via Karplus-Strong."""
    n = int(SR * dur)
    per = max(2, int(SR / freq))
    buf = np.random.default_rng(int(freq * 13)).uniform(-1, 1, per)
    out = np.empty(n)
    for i in range(n):
        out[i] = buf[i % per]
        buf[i % per] = decay * 0.5 * (buf[i % per] + buf[(i + 1) % per])
    env = np.exp(-np.linspace(0, 4.2, n))
    return out * env


def _kick(dur: float = 0.28) -> np.ndarray:
    """Bumbo: seno com queda de pitch e decaimento exponencial."""
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    f = 110 * np.exp(-t * 22) + 48
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def _hat(dur: float = 0.05) -> np.ndarray:
    """Chimbal: ruído filtrado (high-pass simples por diferença)."""
    rng = np.random.default_rng(7)
    n = int(SR * dur)
    x = rng.uniform(-1, 1, n)
    x = np.diff(x, prepend=0.0)          # realça agudos
    return x * np.exp(-np.linspace(0, 60, n))


ACORDES = [
    (130.81, 164.81, 196.00),   # C (C3 E3 G3)
    (98.00, 123.47, 146.83),    # G (G2 B2 D3)
    (110.00, 130.81, 164.81),   # Am (A2 C3 E3)
    (87.31, 110.00, 130.81),    # F (F2 A2 C3)
]


def gerar_trilha(dur: float, path: Path) -> Path:
    """Gera bed.wav de `dur` segundos (loop dos 4 acordes)."""
    n_total = int(SR * dur)
    bed = np.zeros(n_total)

    t = 0.0
    i_acorde = 0
    while t < dur:
        acorde = ACORDES[i_acorde % len(ACORDES)]
        i_acorde += 1
        # dedilhado: 4 notas por compasso (2 beats), 1 batida de diferença
        for k, nota in enumerate(acorde + (acorde[0] * 2,)):
            ini = int((t + k * BEAT * 0.5) * SR)
            if ini >= n_total:
                break
            tom = _pluck(nota, min(1.2, dur - ini / SR))
            fim = min(n_total, ini + len(tom))
            bed[ini:fim] += tom[: fim - ini] * 0.35
        t += BEAT * 2.0

    # bateria: kick nos beats 1 e 3, hat nos offbeats
    b = 0
    while b * BEAT < dur:
        ini = int(b * BEAT * SR)
        if b % 2 == 0:
            k = _kick()
            fim = min(n_total, ini + len(k))
            bed[ini:fim] += k[: fim - ini] * 0.8
        else:
            h = _hat()
            fim = min(n_total, ini + len(h))
            bed[ini:fim] += h[: fim - ini] * 0.12
        b += 1

    # fades globais para o bed não "entrar saindo" em loop
    fade = int(0.15 * SR)
    if n_total > 2 * fade:
        rampa = np.linspace(0, 1, fade)
        bed[:fade] *= rampa
        bed[-fade:] *= rampa[::-1]

    pico = np.max(np.abs(bed)) or 1.0
    bed = bed * (PICO / pico)

    # grava WAV float32 via scipy (já instalado; sem dependência extra)
    from scipy.io import wavfile
    wavfile.write(str(path), SR, bed.astype(np.float32))
    return path
