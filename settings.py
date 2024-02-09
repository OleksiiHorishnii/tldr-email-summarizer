import yaml

with open('config.yaml', 'r') as file:
    config = yaml.safe_load(file)

MODEL_NAME = config['model_name']
FIELD_CHECKS = config['field_checks']
MAX_RETRIES = config['max_retries']
SECTIONS = config['sections']
TABS = config['tabs']
