from pathlib import Path
import yaml


CONFIG_DIR = Path("config")


def load_yaml(path: str):

    with open(
        CONFIG_DIR / path,
        encoding="utf-8"
    ) as f:
        return yaml.safe_load(f)