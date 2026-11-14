import json

with open('{{artifact:fabfae71-b568-46f4-8fc6-df59c3879686}}') as f:
    manifest = json.load(f)

with open('nordcan_api_manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)