"""Install a pinned public local planner checkpoint; no images leave the machine."""
import argparse
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path
import setup_partcrafter as downloader

ROOT=Path(__file__).resolve().parents[2]
MODEL_ID='Qwen/Qwen3-VL-2B-Instruct'
REVISION='89644892e4d85e24eaac8bacfd4f463576704203'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--size',choices=['2b','4b'],default='2b');args=parser.parse_args()
    if args.size=='4b':
        MODEL_ID='Qwen/Qwen3-VL-4B-Instruct';REVISION='ebb281ec70b05090aa6165b016eac8ec08e71b17'
    info_file='qwen3vl_4b_model_info.json'if args.size=='4b'else'qwen3vl_model_info.json'
    info=json.loads((ROOT/'experiments/parts_first_20261114/model_research'/info_file).read_text(encoding='utf-8'))
    if info['sha']!=REVISION or info.get('cardData',{}).get('license')!='apache-2.0':
        raise ValueError('Planner revision or license differs from the reviewed model')
    # Reuse strict Range, blob and full-file validation without changing the
    # PartCrafter installer or any existing model files.
    downloader.MODEL=ROOT/('.models/assembly-vlm-qwen3-'+args.size)
    downloader.REVISION=REVISION
    original_fetch=downloader.fetch
    def fetch(url,*args,**kwargs):
        url=url.replace('/wgsxm/PartCrafter/','/'+MODEL_ID+'/')
        if args or kwargs:return original_fetch(url,*args,**kwargs)
        raw=url.replace('/resolve/','/raw/').split('?')[0]
        failures=[]
        filename=raw.rsplit('/',1)[-1]
        mirrorscope=f'https://www.modelscope.cn/models/{MODEL_ID}/resolve/master/{filename}'
        for candidate in(mirrorscope,raw,url+'&planner_retry=1',raw.replace('hf-mirror.com','huggingface.co')):
            try:
                with urllib.request.urlopen(candidate,timeout=25) as response:return response.read(16*1024*1024)
            except Exception as exc:failures.append(str(exc))
        raise RuntimeError('Public configuration download failed: '+'; '.join(failures))
    downloader.fetch=fetch
    records=[]
    for file in info['siblings']:
        if file['rfilename']=='.gitattributes':continue
        row={'path':file['rfilename'],'type':'file','size':file['size'],'oid':file['blobId']}
        if file.get('lfs'):row['lfs']={'oid':file['lfs']['sha256']}
        reusable=ROOT/'.models/assembly-vlm-qwen3-2b'/row['path'];destination=downloader.MODEL/row['path']
        if args.size=='4b'and not file.get('lfs')and reusable.is_file()and not destination.exists():
            content=reusable.read_bytes()
            if len(content)==row['size']and hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()==row['oid']:
                destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(reusable,destination)
        records.append(downloader.download(row))
    (downloader.MODEL/'provenance.json').write_text(json.dumps({'model_id':MODEL_ID,'model_revision':REVISION,
        'license_from_model_card':'apache-2.0','download_endpoint':downloader.ENDPOINT,
        'configuration_fallback_endpoint':f'https://www.modelscope.cn/models/{MODEL_ID}/resolve/master/',
        'configuration_identity_verification':'Fixed HF git blob hash checked even for reused or fallback files',
        'user_images_submitted':False,'files':records},indent=2),encoding='utf-8')
    print('Local planner weights verified',flush=True)
