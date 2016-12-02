import json

def flatten_payload(payload):
    return json.dumps(payload, separators=(',', ':'), sort_keys=True)
