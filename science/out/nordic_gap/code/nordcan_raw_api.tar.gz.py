import os
import shutil
import tarfile

os.makedirs("raw_api", exist_ok=True)

files = {
    "raw_api/manifest.json": "{{artifact:fabfae71-b568-46f4-8fc6-df59c3879686}}",
    "raw_api/survival_cancer160_sex2.json": "{{artifact:7eb6de9a-946d-43ae-a2d5-5308b1f700d4}}",
    "raw_api/survival_cancer110_sex2.json": "{{artifact:e1d723f5-7e1f-4d3b-9965-d0d95a47fd2e}}",
    "raw_api/survival_cancer130_sex1.json": "{{artifact:c5ff201b-d495-456a-afdc-4384f67cc2e0}}",
    "raw_api/survival_cancer110_sex1.json": "{{artifact:707ff543-501a-472c-85d8-ca8ce79f5c4b}}",
    "raw_api/survival_cancer160_sex1.json": "{{artifact:aaaa3fe3-cbbc-4c4f-82f2-db78b0111bc9}}",
    "raw_api/survival_cancer130_sex2.json": "{{artifact:f3052fcd-ef30-4539-9db7-d6869bc2a537}}",
}

for dest, src in files.items():
    shutil.copy(src, dest)

with tarfile.open("nordcan_raw_api.tar.gz", "w:gz") as tar:
    tar.add("raw_api")