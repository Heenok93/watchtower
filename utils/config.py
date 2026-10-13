from pathlib import Path

import yaml


CONFIG_DIR = Path("config")


def load_yaml(filename):

    with open(
        CONFIG_DIR / filename,
        encoding="utf-8"
    ) as f:

        return yaml.safe_load(f)
