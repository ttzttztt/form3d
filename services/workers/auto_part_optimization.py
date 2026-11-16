"""Photo-bound automatic soft-part planning, reconstruction and comparison."""
import argparse,copy,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'services/workers'),str(ROOT/'.tools/geometry_extra')]
import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from shapely.geometry import Polygon,MultiPoint
from services.api.glb_document import read_glb,parts_catalog
from replace_generated_part import selected_group,cushion_slot,replace_generated,write_preview
from photo_part_evidence import scene_meshes,product_mask,fit_camera,associate,paint,project,alpha_polygon,unproject_to_plane,mask_iou,bbox,rasterize,decimate_mesh,constrain_to_photo_rays
from part_registration import observed_pose_surface,basis,surface_samples
from observed_thickness import paired_thickness
from soft_part_repair import fill_paper_pillow,shell_volume_ratio
from reconstruct_parts import intersections,keep_single_solid
from photo_part_evidence import PROJECTION_VERSION
from services.api.part_regeneration import write_json


def cjk_font(size):
    """Pick an installed CJK-capable font on Windows, macOS or Linux."""
    from PIL import ImageFont
    for candidate in ('C:/Windows/Fonts/msyh.ttc','/System/Library/Fonts/PingFang.ttc','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                      '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc','/usr/share/fonts/truetype/wqy/wqy-microhei.ttc'):
        try:return ImageFont.truetype(candidate,size)
        except OSError:continue
    return ImageFont.load_default(size)

def write(path,data):write_json(path,data)

def progress(folder,phase):
    write(folder/'optimization_progress.json',{'phase':phase})
    print('OPTIMIZATION_PHASE '+phase,flush=True)

def setup(folder):
    context=json.loads((folder/'context.json').read_text(encoding='utf-8'))
    doc,binary,extra=read_glb(context['source'])
    group,entries,source=selected_group(doc,binary,context['part_ids'],allow_uv=True)
    return context,doc,binary,extra,group,entries,source

def analysis_scene(doc,binary,group,kind,source,with_frame=True):
    meshes=scene_meshes(doc,binary)
    if kind=='cushion' and with_frame:
        upper,frame,_=cushion_slot(source)
        meshes[group]=decimate_mesh(upper)
        meshes[group+'_analysis_frame']=decimate_mesh(frame)
    return meshes

def photo_pose_surface(source,camera):
    _,_,vh=np.linalg.svd(np.asarray(camera['projection_from_world']));position=vh[-1,:3]/vh[-1,3]
    direction=position-source.centroid;direction/=np.linalg.norm(direction)
    try:return observed_pose_surface(source,'pillow',direction)[0],False
    except ValueError:
        # Keep the same minimum surface support. A stable opposing plane can
        # constrain volume even when the directly visible assignment is torn.
        return observed_pose_surface(source,'pillow')[0],True

def photo_polygon(folder,ref,camera,visible):
    center,axes,_=basis(surface_samples(visible,8000)[0])
    pixels=alpha_polygon(folder/'references'/ref['file'],ref['source_crop_in_product_pixels'])
    polygon=Polygon(unproject_to_plane(pixels,camera['projection_from_world'],center,axes))
    if not polygon.is_valid:polygon=polygon.buffer(0)
    area=MultiPoint((visible.vertices-center)@axes[:,:2]).convex_hull.area
    if polygon.geom_type!='Polygon'or not .45<polygon.area/area<2:
        raise ValueError('强侧向轮廓不适合平面重建')
    return polygon,center,axes


def source_health(source):
    stats={'closed':bool(source.is_watertight),'consistent_winding':bool(source.is_winding_consistent),
           'positive_volume':bool(source.volume>0),'components':len(source.split(only_watertight=False)),
           'self_intersections':int(intersections(source))}
    stats['valid_solid']=bool(stats['closed']and stats['consistent_winding']and stats['positive_volume']and stats['components']==1 and stats['self_intersections']==0)
    return stats


def analyze_extra_views(folder,context,full,meshes,group):
    result=[]
    for index,view in enumerate(context.get('views',[])):
        location=folder/'views'/str(index);refs_folder=location/'references'
        row={'index':index,'image_id':view['image_id'],'role':view['role'],'status':'needs_input'}
        try:
            refs=json.loads((refs_folder/'references.json').read_text(encoding='utf-8'))
            mask=product_mask(view['photo'],refs,location,{'target':view['target']})
            camera=json.loads((location/'camera.json').read_text(encoding='utf-8'))if(location/'camera.json').exists()else{}
            if camera.get('projection_version')!=PROJECTION_VERSION:camera=fit_camera(full,mask);write(location/'camera.json',camera)
            labels=paint(meshes,np.asarray(camera['projection_from_world']),tuple(camera['image_size']),labels=True)
            association,hint=associate(meshes,camera,refs,refs_folder,group,labels)
            cv2.imwrite(str(location/'hint.png'),hint.astype('uint8')*255);cv2.imwrite(str(location/'other.png'),((labels>0)&~hint).astype('uint8')*255)
            overlay=np.array(Image.open(refs_folder/'product.png').convert('RGB'))
            cv2.drawContours(overlay,cv2.findContours(hint.astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0],-1,(20,150,255),3)
            ref=next((c for c in refs['candidates']if c['id']==association.get('candidate_id')),None)
            if ref:
                expected=cv2.imread(str(refs_folder/ref['mask_file']),0)>127
                cv2.drawContours(overlay,cv2.findContours(expected.astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0],-1,(30,200,80),2)
            Image.fromarray(overlay).save(location/'association.png')
            reliable=association['status']=='matched'and camera['silhouette_iou']>=.65 and association.get('visible_mask_iou',0)>=.65
            row.update(status='matched'if reliable else'needs_input',association=association,camera_silhouette_iou=camera['silhouette_iou'],needs_guided_reference=camera['silhouette_iou']>=.65 and not reliable and not(location/'guided_done').exists(),same_product_identity_verified=False)
            if not reliable:row['reason']='补充图中的整件轮廓或部件对应不足，未将相似家具视为同款证据'
        except(ValueError,OSError,KeyError)as exc:row.update(reason=str(exc)if isinstance(exc,ValueError)else'补充图未得到可对应的部件参考',needs_guided_reference=False)
        write(location/'analysis.json',row);result.append(row)
    return result

def analyze(folder):
    context,doc,binary,_,group,entries,source=setup(folder)
    refs_folder=folder/'references';refs=json.loads((refs_folder/'references.json').read_text(encoding='utf-8'))
    mask=product_mask(context['photo'],refs,context['source_folder'],context['original_request'])
    full=scene_meshes(doc,binary)
    camera=json.loads((folder/'camera.json').read_text(encoding='utf-8'))if(folder/'camera.json').exists()else{}
    if camera.get('projection_version')!=PROJECTION_VERSION:camera=fit_camera(full,mask);write(folder/'camera.json',camera)
    meshes=analysis_scene(doc,binary,group,context['kind'],source,context.get('seat_with_frame',True))
    labels=paint(meshes,np.asarray(camera['projection_from_world']),tuple(camera['image_size']),labels=True)
    association,visible=associate(meshes,camera,refs,refs_folder,group,labels)
    cv2.imwrite(str(folder/'hint.png'),visible.astype('uint8')*255)
    cv2.imwrite(str(folder/'other.png'),((labels>0)&~visible).astype('uint8')*255)
    reference=next((c for c in refs['candidates']if c['id']==association.get('candidate_id')),None)
    rgb=np.array(Image.open(refs_folder/'product.png').convert('RGB'));overlay=rgb.copy()
    cv2.drawContours(overlay,cv2.findContours(visible.astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0],-1,(20,150,255),3)
    if reference:
        reference_mask=cv2.imread(str(refs_folder/reference['mask_file']),0)>127
        cv2.drawContours(overlay,cv2.findContours(reference_mask.astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0],-1,(30,200,80),2)
    Image.fromarray(overlay).save(folder/'association.png')
    plan={'route':'needs_input','reason':'部件与原图对应不确定，请检查参考图','photo_association':association,'kind':context['kind'],'source_closed':bool(source.is_watertight)}
    if association['status']=='matched':
        health=source_health(source);plan['source_geometry_checks']=health
        supported=health['valid_solid']and shell_volume_ratio(source)>.35 and association['visible_mask_iou']>.65
        if context['kind']=='cushion':
            if context.get('seat_with_frame',True):plan.update(route='source_seam',reason='已有坐面与接缝，按原图检查轮廓并局部修复')
            elif supported:plan.update(route='keep',reason='现有坐垫为完整闭合体且轮廓有支持，保留原形')
            else:plan.update(route='ai_regeneration',reason='独立坐垫仍有残缺或轮廓不足，使用对应参考重新生成')
        elif context['kind']=='pillow':
            if supported:
                plan.update(route='keep',reason='现有部件闭合且轮廓有支持，保留原形')
            else:
                try:
                    visible_surface,fallback=photo_pose_surface(source,camera)
                    plan['opposing_plane_fallback']=fallback
                    measure=paired_thickness(source,visible_surface)
                    if not measure:raise ValueError('缺少可靠的前后表面，使用对应参考重新生成')
                    photo_polygon(folder,reference,camera,visible_surface)
                except ValueError as exc:plan.update(route='ai_regeneration',reason=str(exc)+'；使用对应部件参考重新生成'if '重新生成'not in str(exc)else str(exc))
                else:plan.update(route='photo_pillow',reason='前后表面有支持，按对应原图轮廓重建并保留软边',thickness=measure)
        elif supported:plan.update(route='keep',reason='现有圆柱抱枕为完整闭合体且轮廓有支持，保留原形')
        else:plan.update(route='ai_regeneration',reason='圆柱抱枕仍有残缺或轮廓不足，使用对应参考重新生成')
    plan['needs_guided_reference']=camera['silhouette_iou']>=.65 and (association['status']!='matched' or association.get('visible_mask_iou',0)<.65) and not (folder/'guided_done').exists()
    plan['additional_views']=analyze_extra_views(folder,context,full,meshes,group)
    if any(v['status']!='matched'for v in plan['additional_views']):
        plan.update(route='needs_input',reason='补充视图与部件尚未可靠对应，未忽略补充证据继续生成')
    write(folder/'analysis.json',plan)
    return plan

def paint_image(meshes,matrix,size,target):
    return rasterize(meshes,matrix,size,target)[1]

def compare(folder,context,before_doc,before_binary,after_doc,after_binary,old_group,new_group,operation,plan):
    camera=json.loads((folder/'camera.json').read_text(encoding='utf-8'));matrix=np.asarray(camera['projection_from_world']);size=tuple(camera['image_size'])
    _,_,source=selected_group(before_doc,before_binary,context['part_ids'],allow_uv=True)
    before=analysis_scene(before_doc,before_binary,old_group,context['kind'],source,context.get('seat_with_frame',True))
    after=scene_meshes(after_doc,after_binary)
    blabels,image_before=rasterize(before,matrix,size,old_group)
    alabels,image_after=rasterize(after,matrix,size,new_group)
    bmask=blabels==list(before).index(old_group)+1
    amask=alabels==list(after).index(new_group)+1
    refs=json.loads((folder/'references/references.json').read_text(encoding='utf-8'))
    ref=next(c for c in refs['candidates']if c['id']==plan['photo_association']['candidate_id'])
    expected=cv2.imread(str(folder/'references'/ref['mask_file']),0)>127
    score_before=mask_iou(expected,bmask);score_after=mask_iou(expected,amask)
    original=np.asarray(Image.open(folder/'references/product.png').convert('RGB'))
    region=bbox(expected|bmask|amask);padding=max(region[2:]-region[:2])*.1
    region=np.rint([max(0,region[0]-padding),max(0,region[1]-padding),min(size[0],region[2]+padding),min(size[1],region[3]+padding)]).astype(int)
    canvas=Image.new('RGB',(1200,440),'white');draw=ImageDraw.Draw(canvas)
    font=cjk_font(20)
    from PIL import ImageOps
    for i,(label,image)in enumerate([('原图',original),('优化前',image_before),('优化后',image_after)]):
        crop=Image.fromarray(image).crop(tuple(region));crop=ImageOps.contain(crop,(390,390));canvas.paste(crop,(i*400+(400-crop.width)//2,42+(390-crop.height)//2));draw.text((i*400+15,8),label,fill='#24334d',font=font)
    canvas.save(folder/'comparison.png')
    Image.fromarray(image_before).save(folder/'before.png');Image.fromarray(image_after).save(folder/'after.png')
    checks={'camera_silhouette_iou':camera['silhouette_iou'],'part_silhouette_iou_before':score_before,'part_silhouette_iou_after':score_after,'same_projection_before_after':True,'visibility_method':'per_pixel_perspective_correct_depth','metric_is_not_product_accuracy':True}
    views=[{'role':'primary','part_silhouette_iou_before':score_before,'part_silhouette_iou_after':score_after,'passed':score_after>=max(.65,score_before-.03),'additional_reference':False,'capture_independence_verified':False}]
    for view in plan.get('additional_views',[]):
        location=folder/'views'/str(view['index']);vc=json.loads((location/'camera.json').read_text(encoding='utf-8'));vm=np.asarray(vc['projection_from_world']);vs=tuple(vc['image_size'])
        refs=json.loads((location/'references/references.json').read_text(encoding='utf-8'));ref=next(c for c in refs['candidates']if c['id']==view['association']['candidate_id'])
        expected_view=cv2.imread(str(location/'references'/ref['mask_file']),0)>127
        bl,bi=rasterize(before,vm,vs,old_group);al,ai=rasterize(after,vm,vs,new_group)
        bs=mask_iou(expected_view,bl==list(before).index(old_group)+1);aps=mask_iou(expected_view,al==list(after).index(new_group)+1)
        Image.fromarray(bi).save(location/'before.png');Image.fromarray(ai).save(location/'after.png')
        views.append({'index':view['index'],'image_id':view['image_id'],'role':view['role'],'part_silhouette_iou_before':bs,'part_silhouette_iou_after':aps,'passed':aps>=max(.65,bs-.03),'additional_reference':True,'capture_independence_verified':False})
    checks['views']=views
    passed=all(v['passed']for v in views)
    checks['can_adopt']=bool(passed and plan['route']!='keep')
    checks['reason']='现有部件保留原形，无需采用替换'if plan['route']=='keep'else'当前视角轮廓检查通过，仍需查看侧面和底面'if passed else'优化后轮廓未通过检查，候选保留但不能替换'
    from candidate_quality import assess_candidate
    _,_,result_mesh=selected_group(after_doc,after_binary,[p['id']for p in parts_catalog(after_doc)if(p.get('logical_group_id')or p['id'])==new_group],allow_uv=True)
    assessment=assess_candidate(result_mesh,source,before_doc,before_binary,context['part_ids'],views,context.get('target_faces',100000),operation)
    checks['quality_dimensions']=assessment['dimensions'];checks['ranking']=assessment['ranking']
    if not assessment['eligible']:
        checks.update(can_adopt=False,reason='完整性或相邻部件穿插检查未通过，原模型保留')
    write(folder/'checks.json',checks)
    return checks

def optimize(folder):
    progress(folder,'reading_source')
    context,doc,binary,extra,group,entries,source=setup(folder)
    before_doc=copy.deepcopy(doc);before_binary=bytearray(binary)
    plan=json.loads((folder/'analysis.json').read_text(encoding='utf-8'))
    if plan['route']=='needs_input':return None
    refs=json.loads((folder/'references/references.json').read_text(encoding='utf-8'))
    ref=next(c for c in refs['candidates']if c['id']==plan['photo_association']['candidate_id'])
    camera=json.loads((folder/'camera.json').read_text(encoding='utf-8'))
    if camera.get('projection_version')!=PROJECTION_VERSION:raise ValueError('投影轮廓算法已更新，请重新分析；本次生成部件保留')
    photo={'rgb':np.asarray(Image.open(folder/'references/product.png').convert('RGB')),'projection_from_world':camera['projection_from_world'],'mask':cv2.imread(str(folder/'references'/ref['mask_file']),0)>127}
    request={'kind':context['kind'],'part_ids':context['part_ids'],'_allow_uv_rebuild':True,'_progress':lambda phase:progress(folder,phase)}
    if plan['route']=='source_seam':
        operation=replace_generated(doc,binary,{**request,'method':'source_seam','_photo_context':photo})
    elif plan['route']=='photo_pillow':
        visible,_=photo_pose_surface(source,camera);polygon,center,axes=photo_polygon(folder,ref,camera,visible)
        measure=paired_thickness(source,visible)
        candidate,repair=fill_paper_pillow(source,source,{'thickness_constraint':measure},polygon,True,visible)
        repair.update(photo_candidate_id=ref['id'],photo_contour_vertices=len(polygon.exterior.coords)-1)
        # Use the exact same plane orientation as the paired-height builder.
        normal=visible.face_normals.mean(0)
        if axes[:,2]@normal<0:axes[:,2]*=-1
        candidate,ray_constraint=constrain_to_photo_rays(candidate,camera['projection_from_world'],center,axes,min(np.linalg.norm(source.extents)*.3,measure['core_thickness_source_units']*2))
        repair['photo_ray_constraint']=ray_constraint
        candidate.export(folder/'analysis_candidate.glb')
        from storage_contacts import clean_storage_contacts
        candidate,cleanup=clean_storage_contacts(candidate)
        if cleanup:repair['storage_contact_cleanup']=cleanup
        operation=replace_generated(doc,binary,{**request,'_prepared_world':True,'_placement':{'method':'photo_contour_and_observed_depth','pose_is_estimated':True,'real_scale_verified':False,'thickness_constraint':measure},'_surface_repair':repair},candidate)
    elif plan['route']=='ai_regeneration':
        progress(folder,'reading_candidate')
        candidate=__import__('trimesh').load(folder/'generated/model.glb',force='mesh',process=False)
        from solid_partition import prepare_mesh
        candidate,_=prepare_mesh(candidate);candidate,generated_cleanup=keep_single_solid(candidate)
        from shape_simplification import simplify_shape
        progress(folder,'simplifying')
        candidate,simplification=simplify_shape(candidate,context.get('target_faces',100000))
        others={key:value for key,value in scene_meshes(doc,binary).items()if key!=group}
        pose_views=[{'matrix':camera['projection_from_world'],'mask':photo['mask'],'others':others}]
        for view in plan.get('additional_views',[]):
            location=folder/'views'/str(view['index']);vc=json.loads((location/'camera.json').read_text(encoding='utf-8'));vr=json.loads((location/'references/references.json').read_text(encoding='utf-8'));rf=next(c for c in vr['candidates']if c['id']==view['association']['candidate_id'])
            pose_views.append({'matrix':vc['projection_from_world'],'mask':cv2.imread(str(location/'references'/rf['mask_file']),0)>127,'others':others})
        request['_photo_pose_views']=pose_views
        operation=replace_generated(doc,binary,request,candidate)
        operation['simplification']=simplification
        operation['generated_component_cleanup']=generated_cleanup
    else:
        operation={'operation':'replace_part','method':'keep','kind':context['kind'],'part_group_ids':[group],'source_group_id':group,'slot':None,'surface_repair':None,'unrelated_groups_unchanged':True,'appearance_review':'unreviewed'}
    operation['automatic_plan']=plan
    if plan['route']!='keep':
        progress(folder,'preparing_uv')
        from replacement_uv import prepare_replacement_uv
        operation['material_readiness']=prepare_replacement_uv(doc,binary,operation['part_group_ids'])
    progress(folder,'checking_views_and_neighbors');checks=compare(folder,context,before_doc,before_binary,doc,binary,group,operation['part_group_ids'][0],operation,plan)
    operation['photo_checks']=checks
    progress(folder,'writing_preview');write_preview(doc,binary,extra,operation,folder/'preview',hashlib.sha256(Path(context['source']).read_bytes()).hexdigest())
    return checks

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',required=True);p.add_argument('--stage',choices=['analyze','optimize'],required=True);args=p.parse_args()
    value=analyze(Path(args.folder))if args.stage=='analyze'else optimize(Path(args.folder));print(json.dumps(value,ensure_ascii=False),flush=True)
