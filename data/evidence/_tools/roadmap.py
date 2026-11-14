import re,json,sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
L=(ROOT / 'res/roadmap/r.txt').read_text(encoding='utf-8').split('\n')
want=['1.3.2','2.3.1','2.3.2','2.3.3','2.3.4','2.5.1','2.5.2','2.5.3','3.1.1','3.1.2','3.1.3','3.1.4','3.2.1','3.2.2','3.2.3','3.2.4','3.5.1','3.5.2','3.5.3','3.5.4','3.5.5']
starts=[(i,m.group(1)) for i,l in enumerate(L) if (m:=re.match(r'\s*Toimenpide (\d\.\d\.\d) ',l))]
def clean(s): return re.sub(r'\s+',' ',s.replace('­','')).strip()
out=[]
for k,(i,mid) in enumerate(starts):
    if mid not in want: continue
    end=starts[k+1][0] if k+1<len(starts) else i+120
    # stop at next section heading "Osatavoite"/"Tavoite"
    for j in range(i+1,end):
        if re.match(r'\s*(Osatavoite|TAVOITE|Tavoite) \d',L[j]): end=j;break
    blk=L[i:end]
    # title: lines until blank
    t=[];j=0
    while j<len(blk) and blk[j].strip(): t.append(blk[j]);j+=1
    title=clean(' '.join(t)).replace('Toimenpide '+mid+' ','')
    fields={}
    cur=None
    for n,l in enumerate(blk[j:],start=i+j):
        m=re.match(r'\s*(Vastuutaho|Aikataulu|Mittari|Resurssi|Resurssit|Rahoitus|Kustannus\w*):\s*(.*)',l)
        if m:
            cur=m.group(1); fields.setdefault(cur,[]).append([n+1,m.group(2)])
        elif cur and l.strip(): fields[cur][-1][1]+=' '+l.strip()
        elif not l.strip(): cur=None if cur in('Vastuutaho','Mittari','Resurssi','Resurssit') else cur
    body=clean(' '.join(blk[j:]))
    out.append(dict(id=mid,line_start=i+1,line_end=end,title_fi=title,fields={k:[[n,clean(v)] for n,v in vs] for k,vs in fields.items()},body_head=body[:700]))
json.dump(out, open(ROOT / 'data/evidence/_tools/roadmap_raw.json', 'w'), ensure_ascii=False, indent=1)
for o in out:
    print('##',o['id'],o['line_start'],o['line_end'],'|',o['title_fi'])
    for k,vs in o['fields'].items():
        for n,v in vs: print('  ',k,n,':',v[:330])
    print('   BODY:',o['body_head'][:420])
