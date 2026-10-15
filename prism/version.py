"""Версии кода и моделей — часть аудиторского следа каждой оценки."""
from __future__ import annotations

import hashlib
import subprocess
from functools import lru_cache
from pathlib import Path

PACKAGE_VERSION = "0.1.0"

# Версия модели меняется при любом изменении, способном сдвинуть результат.
MODEL_VERSIONS = {
    "curves.bootstrap": "1.0",       # глобальный подбор, ступени ЦБ, monotone convex
    "vol.fx_surface": "1.0",         # дельта-столпы → SVI, интерполяция по общей дисперсии
    "vol.local_vol": "1.0",          # Дюпир по SVI-поверхности
    "analytic.fx": "1.0",            # GK со смайлом, RR + VV, касания, двойные барьеры
    "analytic.rates": "1.0",         # мультикривая, Башелье
    "mc.engine": "1.0",              # пути, мост Брауна, LSMC
    "rates.hw_tree": "1.0",          # дерево Hull-White
    "pde.fd1d": "1.0",
    "xva": "1.0",
    "decomposition": "1.0",
}

ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def source_hash() -> str:
    """Хэш исходного кода и данных пакета (для воспроизводимости без git)."""
    h = hashlib.sha256()
    for p in sorted(ROOT.rglob("*")):
        if p.is_file() and p.suffix in (".py", ".json", ".yaml", ".yml") and "__pycache__" not in p.parts:
            h.update(str(p.relative_to(ROOT)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


@lru_cache(maxsize=1)
def git_info() -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=ROOT, capture_output=True, text=True,
                                    timeout=5).stdout.strip())
        return {"commit": commit or None, "dirty": dirty}
    except Exception:  # pragma: no cover
        return {"commit": None, "dirty": None}


def code_version() -> dict:
    return {"package_version": PACKAGE_VERSION, **git_info(), "source_hash": source_hash()}
