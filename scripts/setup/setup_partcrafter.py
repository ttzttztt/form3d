# -*- coding: utf-8 -*-
"""Download public pinned PartCrafter weights only, never submit user images."""
import concurrent.futures,hashlib,json,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
MODEL=ROOT/'.models/partcrafter'
RESEARCH=ROOT/'experiments/parts_first_20261114/model_research'
REVISION='69a0ffc1dad5e48e7e5ed91c0609f2b1276eb31f'
ENDPOINT='https://hf-mirror.com'
CHUNK=4*1024*1024

def digest(path):
    result=hashlib.sha256()
    with path.open('rb')as stream:
        for data in iter(lambda:stream.read(CHUNK),b''):result.update(data)
    return result.hexdigest()

def fetch(url,start=None,end=None,total=None):
    headers={'User-Agent':'img3d-local-parts-evaluation'}
    if start is not None:headers['Range']=f'bytes={start}-{end}'
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=45)as response:
        if start is not None and response.headers.get('Content-Range')!=f'bytes {start}-{end}/{total}':raise ValueError('Weight range mismatch')
        data=response.read(end-start+2 if start is not None else 2*1024*1024)
    if start is not None and len(data)!=end-start+1:raise ValueError('Truncated weight range')
    return data

def download(row):
    path=MODEL/row['path'];path.parent.mkdir(parents=True,exist_ok=True)
    size=row['size'];large=row.get('lfs');url=f'{ENDPOINT}/wgsxm/PartCrafter/resolve/{REVISION}/{row["path"]}?download=true&setup=20261114'
    if path.is_file():
        sha=digest(path)
        valid=sha==large['oid']if large else hashlib.sha1(b'blob '+str(size).encode()+b'\0'+path.read_bytes()).hexdigest()==row['oid']
        if not valid or path.stat().st_size!=size:raise ValueError('Existing model file differs: '+row['path'])
        print('verified cache',row['path'],flush=True);return{'path':row['path'],'sha256':sha,'bytes':size}
    if not large:
        content=fetch(url)
        if len(content)!=size or hashlib.sha1(b'blob '+str(size).encode()+b'\0'+content).hexdigest()!=row['oid']:raise ValueError('Configuration provenance mismatch: '+row['path'])
        path.write_bytes(content)
    else:
        count=(size+CHUNK-1)//CHUNK
        def block(index):
            start=index*CHUNK;end=min(size,start+CHUNK)-1;part=path.with_name(path.name+f'.part{index:04d}')
            if part.is_file()and part.stat().st_size==end-start+1:return
            for attempt in range(5):
                try:
                    content=fetch(url+f'&part={index}&attempt={attempt}',start,end,size);part.write_bytes(content);return
                except Exception:
                    if attempt==4:raise
                    time.sleep(attempt+1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10)as executor:
            for done,future in enumerate(concurrent.futures.as_completed([executor.submit(block,n)for n in range(count)]),1):
                future.result()
                if done%32==0 or done==count:print(row['path'],done,'/',count,flush=True)
        assembled=path.with_name(path.name+'.download')
        with assembled.open('wb')as output:
            for n in range(count):
                part=path.with_name(path.name+f'.part{n:04d}')
                with part.open('rb')as stream:
                    for data in iter(lambda:stream.read(CHUNK),b''):output.write(data)
        if digest(assembled)!=large['oid']:raise ValueError('Model weight SHA-256 mismatch: '+row['path'])
        assembled.replace(path)
        # Delete only this downloader's chunk files after full-file hash proof.
        for n in range(count):path.with_name(path.name+f'.part{n:04d}').unlink()
    return{'path':row['path'],'sha256':digest(path),'bytes':size}

if __name__=='__main__':
    rows=json.loads((RESEARCH/'weights_tree.json').read_text(encoding='utf-8'))
    records=[]
    for row in rows:
        if row['type']=='file'and row['path']!='.gitattributes':records.append(download(row))
    (MODEL/'provenance.json').write_text(json.dumps({'model_id':'wgsxm/PartCrafter','model_revision':REVISION,'source_revision':'3d773bf02fad51c7ab31a5615573fec93b287b30','license_from_model_card':'MIT','download_endpoint':ENDPOINT,'user_images_submitted':False,'files':records},indent=2),encoding='utf-8')
    print('All model files hash-verified',flush=True)
