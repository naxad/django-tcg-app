# utils/set_symbols.py
import os, re

def _norm_key(name: str) -> str:
    s = name.lower()
    s = re.sub(r'[^a-z0-9]+', '_', s).strip('_')
    return s

def load_symbol_assets(dir_path: str) -> dict[str, str]:
    """
    Scans a directory for .png files and returns:
      { normalized_key: filename }
    Example key: 'prismatic_evolutions' -> 'Prismatic_Evolutions.png'
    """
    mapping = {}
    for fn in os.listdir(dir_path):
        if not fn.lower().endswith(".png"):
            continue
        stem = os.path.splitext(fn)[0]
        mapping[_norm_key(stem)] = fn
    return mapping
