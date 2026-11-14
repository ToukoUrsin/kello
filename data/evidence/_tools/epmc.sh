#!/bin/bash
# usage: epmc.sh slug query   -> saves abstract + fulltext (if OA) as page.txt
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
R="$ROOT/data/raw/evidence"; d="$R/$1"; mkdir -p "$d"
curl -sG --max-time 40 "https://www.ebi.ac.uk/europepmc/webservices/rest/search" --data-urlencode "query=$2" --data-urlencode "format=json" --data-urlencode "resultType=core" --data-urlencode "pageSize=1" -o "$d/meta.json"
python3 -I - "$d" <<'PY'
import json,sys,subprocess,re,os
d=sys.argv[1]
j=json.load(open(d+'/meta.json'))
r=(j.get('resultList',{}).get('result') or [None])[0]
if not r: print(os.path.basename(d),'NO RESULT'); sys.exit()
out=f"TITLE: {r.get('title')}\nAUTHORS: {r.get('authorString')}\nJOURNAL: {r.get('journalInfo',{}).get('journal',{}).get('title')} {r.get('pubYear')}\nDOI: {r.get('doi')} PMID: {r.get('pmid')} PMCID: {r.get('pmcid')}\nABSTRACT: {re.sub(r'</?[a-zA-Z][^>]*>','',r.get('abstractText') or '')}\n\n"
pmc=r.get('pmcid'); ft=''
if pmc:
    x=subprocess.run(['curl','-s','--max-time','60',f'https://www.ebi.ac.uk/europepmc/webservices/rest/{pmc}/fullTextXML'],capture_output=True,text=True).stdout
    open(d+'/full.xml','w').write(x)
    ft=re.sub(r'\s+',' ',re.sub('<[^>]+>',' ',x))
open(d+'/page.txt','w').write(out+"FULLTEXT: "+ft)
print(os.path.basename(d),r.get('title')[:70],r.get('pubYear'),pmc,len(ft))
PY
