"""Reprocess saved proposals, explicitly recording that no AI inference is repeated."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from services.api.assembly_proposals import normalize_proposal
from generate_partcrafter import digest,write

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    source=Path(args.source);output=Path(args.output)
    if output.exists():raise ValueError('Do not overwrite a previous proposal derivation')
    output.mkdir(parents=True);rows=[]
    for path in sorted(source.glob('*/semantic_proposal.json')):
        saved=json.loads(path.read_text(encoding='utf-8'));folder=output/path.parent.name;folder.mkdir()
        if saved['status']=='proposal_ready':
            try:
                normalized,warnings=normalize_proposal({'furniture':saved['furniture']})
                saved.update(**normalized,normalization_warnings=warnings)
            except ValueError as exc:saved.update(status='failed',error=str(exc))
        saved.update(is_new_sampling=False,derivation='conservative_label_aliases',source_proposal_sha256=digest(path))
        write(folder/'semantic_proposal.json',saved);rows.append({'case':path.parent.name,'status':saved['status']})
    write(output/'run.json',{'is_new_sampling':False,'cases':rows})
