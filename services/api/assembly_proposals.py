"""Conservative label normalization; never invent a missing furniture part."""
import copy,math

KINDS={'seat_cushion','back_cushion','bolster','backrest','armrest','frame','body','leg','tabletop','door','drawer','shelf','panel','other','unknown'}
ALIASES={'top':'tabletop','table_top':'tabletop','table top':'tabletop','pillow':'back_cushion',
         'throw_pillow':'back_cushion','cylindrical_pillow':'bolster','table_leg':'leg','cabinet_door':'door','chair_back':'backrest',
         'upholstered_body':'body','sofa_body':'body','seat_body':'body'}


def normalize_proposal(value):
    result=copy.deepcopy(value);warnings=[]
    if not isinstance(result,dict)or not isinstance(result.get('furniture'),list):raise ValueError('No furniture list')
    for furniture in result['furniture']:
        if furniture.get('category')not in('sofa','chair','table','cabinet','other'):raise ValueError('Unsupported category')
        if not isinstance(furniture.get('parts'),list)or len(furniture['parts'])>64:raise ValueError('Invalid part inventory')
        seen=set()
        for item in [furniture]+furniture['parts']:
            box=item.get('bbox')
            if not isinstance(box,list)or len(box)!=4 or any(type(v)not in(int,float)or not math.isfinite(v)or not 0<=v<=1000 for v in box)or box[2]<=box[0]or box[3]<=box[1]:raise ValueError('Invalid normalized box')
        for part in furniture['parts']:
            raw=part.get('kind');kind=ALIASES.get(raw,raw)
            if kind not in KINDS:kind='unknown';warnings.append('Unrecognized part label preserved as unknown: '+str(raw))
            if kind!=raw:part['raw_kind']=raw
            part['kind']=kind;key=(kind,tuple(part['bbox']))
            if key in seen:raise ValueError('Repeated identical semantic part')
            seen.add(key)
    return result,warnings
