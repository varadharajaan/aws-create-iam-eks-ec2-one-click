import json
import re

with open("aws_accounts_config.json") as f:
    config = json.load(f)

def mask(value):
    return value[:5] + "*" * (len(value) - 10) + value[-5:]

for acc in config["accounts"].values():
    acc["access_key"] = mask(acc["access_key"])
    acc["secret_key"] = mask(acc["secret_key"])

with open("sanitized_aws_accounts_config.json", "w") as f:
    json.dump(config, f, indent=2)
