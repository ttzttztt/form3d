"""Output state and category resolution without importing ML libraries."""

class OutputNeedsAttention(ValueError):
    pass

def target_category(request,image=None):
    if request.get('object_category'):return request['object_category']
    label=request.get('object_label','').lower()
    for keywords,category in [(('花瓶','vase'),'vase'),(('盆栽','plant'),'plant'),(('沙发','扶手椅','sofa','armchair'),'sofa'),
                              (('柜','bookcase','cabinet'),'cabinet'),(('桌','table'),'table'),(('椅','chair'),'chair'),(('灯','lamp'),'lamp')]:
        if any(word in label for word in keywords):return category
    if image and request.get('object_id'):
        obj=next((obj for obj in image.get('analysis',{}).get('objects',[]) if obj['id']==request['object_id']),None)
        if obj:return obj['category']
    return 'unknown'
