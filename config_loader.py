"""配置加载。"""

from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / '.env')


def load_config(config_path='config.yaml'):
    with open(config_path, encoding='utf-8') as f:
        return yaml.safe_load(f)
