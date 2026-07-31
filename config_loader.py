"""配置加载。"""

import yaml


def load_config(config_path='config.yaml'):
    with open(config_path, encoding='utf-8') as f:
        return yaml.safe_load(f)
