import os
from pathlib import Path


def data_root():
    root = Path(os.environ.get("PIKKABPE_DATA", Path(os.environ.get("LOCALAPPDATA", Path.home())) / "pikkaBPE"))
    root.mkdir(parents=True, exist_ok=True)
    for name in ("evidence", "datasets", "models", "logs", "updates", "backups"):
        (root / name).mkdir(exist_ok=True)
    return root
