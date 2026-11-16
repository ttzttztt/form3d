"""Approximate single-view projection and conservative photo/part association.

This is silhouette fitting, not calibrated photogrammetry or product accuracy.
"""
import json
from pathlib import Path
import cv2
import numpy as np
import trimesh
from scipy.ndimage import binary_fill_holes
PROJECTION_VERSION='triangle_union_and_perspective_depth_v2'

def product_mask(original, references, source_folder, request):
    from PIL import Image
    from local3d_preprocess import remove_product_background
    image = Image.open(original).convert('RGBA')
    crop = references['product_crop_pixels']; product = image.crop(crop)
    segmented = Path(source_folder)/'segmented.png'
    if segmented.is_file():
        t = request['target']; w, h = image.size
        bounds = [round(t['x']*w), round(t['y']*h), round((t['x']+t['width'])*w), round((t['y']+t['height'])*h)]
        alpha = Image.open(segmented).convert('RGBA').getchannel('A')
        if alpha.size != (bounds[2]-bounds[0], bounds[3]-bounds[1]):
            raise ValueError('整件分割与参考坐标不一致，未自动对应部件')
        canvas = Image.new('L', product.size)
        canvas.paste(alpha, (bounds[0]-crop[0], bounds[1]-crop[1]))
        return np.asarray(canvas) > 128
    whole=references.get('whole_product_mask')
    if whole:
        import hashlib
        # The model mask remains a proposal; camera/instance gates still apply.
        folder=Path(source_folder)/'references';path=folder/whole['file']
        if whole['file']!='whole_product_mask.png'or hashlib.sha256(path.read_bytes()).hexdigest()!=whole['sha256']:raise ValueError('补充视图的整件掩码已变化')
        alpha=np.asarray(Image.open(path).convert('L'))>128
        if alpha.shape!=np.asarray(product).shape[:2]or not alpha.any():raise ValueError('补充视图整件轮廓坐标不一致')
        return alpha
    cleaned, method = remove_product_background(product, None, allow_model=False)
    if method not in ('provided_alpha', 'white_background_connected_components'):
        raise ValueError('缺少整件家具的可靠轮廓，请先清理背景')
    return np.asarray(cleaned.getchannel('A')) > 128


def decimate_mesh(mesh,limit=2500):
    import pymeshlab
    mesh=mesh.copy();mesh.merge_vertices(digits_vertex=7);mesh.remove_unreferenced_vertices()
    if len(mesh.faces)>limit:
        ms=pymeshlab.MeshSet();ms.add_mesh(pymeshlab.Mesh(mesh.vertices,mesh.faces.astype(np.int32)))
        ms.meshing_decimation_quadric_edge_collapse(targetfacenum=limit,preservenormal=True)
        current=ms.current_mesh();mesh=trimesh.Trimesh(current.vertex_matrix(),current.face_matrix(),process=False)
    return mesh

def scene_meshes(doc, binary, limit=2500):
    from services.api.glb_document import parts_catalog
    from furniture_parts import primitive_data
    groups = {}
    for part in parts_catalog(doc):
        primitive = doc['meshes'][doc['nodes'][part['node']]['mesh']]['primitives'][part['primitive']]
        _, faces, world, _, _, _ = primitive_data(doc, binary, part, primitive)
        key = part.get('logical_group_id') or part['id']
        groups.setdefault(key, []).append(trimesh.Trimesh(world, faces, process=False))
    result = {}
    for key, meshes in groups.items():
        result[key] = decimate_mesh(trimesh.util.concatenate(meshes),limit)
    return result


def camera_matrix(center, radius, azimuth, elevation, fov):
    distance = radius * 2.8
    position = center + distance*np.array([np.sin(azimuth)*np.cos(elevation), np.sin(elevation), np.cos(azimuth)*np.cos(elevation)])
    forward = (center-position)/np.linalg.norm(center-position)
    right = np.cross(forward, [0., 1., 0.]); right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    rotation = np.stack([right, -up, forward])
    extrinsic = np.c_[rotation, -rotation@position]
    focal = 128/np.tan(fov/2)
    intrinsic = np.array([[focal, 0., 128.], [0., focal, 128.], [0., 0., 1.]])
    return intrinsic@extrinsic


def project(vertices, matrix):
    homogeneous = np.c_[vertices, np.ones(len(vertices))]@matrix.T
    return homogeneous[:, :2]/homogeneous[:, 2:3], homogeneous[:, 2]


def paint(meshes, matrix, size=(256, 256), labels=False):
    if labels:return rasterize(meshes,matrix,size)[0]
    canvas = np.zeros(size[::-1], np.uint8)
    for mesh in meshes.values():
        xy, z = project(mesh.vertices, matrix)
        good = np.all(z[mesh.faces] > 0, axis=1)
        faces = mesh.faces[good]
        tri = np.rint(np.clip(xy[faces], -4096, 4096)).astype(np.int32)
        # fillPoly applies an even/odd rule across overlapping contours. A
        # closed object's front and back must form a union, not cancel out.
        for triangle in tri:cv2.fillConvexPoly(canvas,triangle,1)
    return canvas


def rasterize(meshes,matrix,size,target=None,return_depth=False):
    """Perspective-correct per-pixel depth; no centroid visibility ordering."""
    height,width=size[1],size[0]
    depth_buffer=np.full((height,width),np.inf)
    labels=np.zeros((height,width),np.int32)
    rgb=np.full((height,width,3),245,np.uint8)
    light=np.array([-.3,.8,.6]);light/=np.linalg.norm(light)
    for ordinal,(key,mesh)in enumerate(meshes.items(),1):
        pixels,depth=project(mesh.vertices,matrix)
        base=np.array([226,165,80]if key==target else[185,192,201])
        colors=np.uint8((.6+.35*np.maximum(0,mesh.face_normals@light))[:,None]*base)
        for number,face in enumerate(mesh.faces):
            z=depth[face]
            if np.any(z<=0):continue
            triangle=pixels[face]
            x0,y0=np.maximum(0,np.floor(triangle.min(0))).astype(int)
            x1,y1=np.minimum([width-1,height-1],np.ceil(triangle.max(0))).astype(int)
            if x1<x0 or y1<y0:continue
            a,b,c=triangle
            denominator=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(denominator)<1e-10:continue
            yy,xx=np.mgrid[y0:y1+1,x0:x1+1];xx=xx+.5;yy=yy+.5
            w0=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/denominator
            w1=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/denominator
            w2=1-w0-w1;inside=(w0>=-1e-8)&(w1>=-1e-8)&(w2>=-1e-8)
            inverse=w0/z[0]+w1/z[1]+w2/z[2]
            local=np.where(inverse>0,1/np.maximum(inverse,1e-20),np.inf)
            buffer=depth_buffer[y0:y1+1,x0:x1+1];visible=inside&(local<buffer)
            buffer[visible]=local[visible];labels[y0:y1+1,x0:x1+1][visible]=ordinal
            rgb[y0:y1+1,x0:x1+1][visible]=colors[number]
    return (labels,rgb,depth_buffer)if return_depth else(labels,rgb)


def bbox(mask):
    yy, xx = np.nonzero(mask)
    if not len(xx):
        raise ValueError('参考轮廓为空')
    return np.array([xx.min(), yy.min(), xx.max()+1, yy.max()+1], float)


def mask_iou(a, b):
    return float(np.logical_and(a, b).sum()/max(np.logical_or(a, b).sum(), 1))

def clean_visible_hint(mask):
    original=int(mask.sum())
    opened=cv2.morphologyEx(mask.astype('uint8'),cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3)))
    count,labels,stats,_=cv2.connectedComponentsWithStats(opened,8)
    if count<2:return mask,1.
    index=1+int(stats[1:,cv2.CC_STAT_AREA].argmax())
    core=labels==index;retained=float(core.sum()/max(original,1))
    if retained<.5:return mask,1.
    core=binary_fill_holes(cv2.morphologyEx(core.astype('uint8'),cv2.MORPH_CLOSE,np.ones((3,3),'uint8'))>0)
    return core,retained


def fit_camera(meshes, product_mask):
    full = trimesh.util.concatenate(list(meshes.values()))
    center = full.bounds.mean(0); radius = float(full.extents.max())
    original_size = product_mask.shape[::-1]
    factor = min(256/original_size[0], 256/original_size[1])
    size = tuple(max(1, round(n*factor)) for n in original_size)
    target = cv2.resize(product_mask.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST)
    target_box = bbox(target); target_center = (target_box[:2]+target_box[2:])/2
    best = None; evaluations = 0
    def evaluate(az, el, fov):
        nonlocal best, evaluations
        base = camera_matrix(center, radius, az, el, fov)
        rendered = paint(meshes, base)
        rb = bbox(rendered)
        scale = min((target_box[2:]-target_box[:2])/(rb[2:]-rb[:2]))
        shift = target_center-(rb[:2]+rb[2:])/2*scale
        affine = np.array([[scale, 0., shift[0]], [0., scale, shift[1]], [0., 0., 1.]])
        matrix = affine@base
        projected = cv2.warpAffine(rendered, affine[:2], size, flags=cv2.INTER_NEAREST)
        score = mask_iou(target, projected)
        evaluations += 1
        row = (score, matrix, az, el, fov)
        if best is None or score > best[0]: best = row
        return row
    for az in np.arange(12)*2*np.pi/12:
        for el in (.15, .4, .7):
            evaluate(az, el, np.deg2rad(35))
    for step in (np.deg2rad(10), np.deg2rad(3)):
        _, _, az, el, fov = best
        for da in (-step, 0, step):
            for de in (-step, 0, step):
                evaluate(az+da, np.clip(el+de, .03, 1.2), fov)
    score, matrix, az, el, fov = best
    matrix = np.diag([1/factor, 1/factor, 1.])@matrix
    return {'projection_from_world': matrix.tolist(), 'silhouette_iou': score,
            'evaluations': evaluations, 'azimuth': az, 'elevation': el,
            'fov': fov, 'image_size': list(original_size),
            'method': 'approximate_perspective_silhouette_fit', 'calibrated': False,
            'projection_version':PROJECTION_VERSION,
            'analysis_meshes_are_decimated': True}


def associate(meshes, camera, references, folder, target_group,projected_labels=None):
    matrix = np.asarray(camera['projection_from_world']); size = tuple(camera['image_size'])
    labels = paint(meshes, matrix, size, labels=True)if projected_labels is None else projected_labels
    target,retained = clean_visible_hint(labels == list(meshes).index(target_group)+1)
    if not target.any():
        return {'status':'needs_confirmation','reason':'所选部件在原图视角不可见，不能自动对应参考'},target
    rows = []
    for ref in references['candidates']:
        if 'source_crop_in_product_pixels' not in ref: continue
        raw=cv2.imread(str(Path(folder)/ref['mask_file']),cv2.IMREAD_GRAYSCALE)
        if raw is None:continue
        mask=raw>127
        if mask.shape != target.shape: continue
        if not mask.any():continue
        _,_,components,_=cv2.connectedComponentsWithStats(mask.astype('uint8'),8)
        dominant=float(components[1:,cv2.CC_STAT_AREA].max()/max(mask.sum(),1))if len(components)>1 else 0.
        holes=float((binary_fill_holes(mask)&~mask).sum()/max(mask.sum(),1))
        contours,_=cv2.findContours(mask.astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        complexity=sum(cv2.arcLength(c,True)for c in contours)/max(np.sqrt(mask.sum()),1)
        clean=bool(references.get('kind')not in('pillow','bolster')or(dominant>=.97 and holes<=.02 and complexity<=10))
        iou = mask_iou(target, mask)
        containment=float(np.logical_and(target,mask).sum()/max(target.sum(),1))
        box_a,box_b=bbox(target),bbox(mask);center_error=float(np.linalg.norm((box_a[:2]+box_a[2:]-box_b[:2]-box_b[2:])/2)/max(np.linalg.norm(box_b[2:]-box_b[:2]),1))
        rows.append({'id': ref['id'], 'iou': iou, 'containment':containment,'center_error':center_error,'clean_mask':clean,'mask_quality':{'dominant_component_fraction':dominant,'hole_area_fraction':holes,'normalized_perimeter':float(complexity)},'detection': ref.get('detection'), 'candidate': ref, 'mask': mask})
    rows.sort(key=lambda row: (row['clean_mask'],row['iou']), reverse=True)
    if not rows:
        return {'status': 'needs_confirmation', 'reason': '参考缺少原图位置，无法自动对应部件'}, target
    best = rows[0]
    # Compare different detected instances, not near-duplicate SAM variants.
    alternatives = [row['iou'] for row in rows if row['clean_mask']and mask_iou(row['mask'],best['mask'])<.25]
    margin = best['iou']-max(alternatives, default=0.)
    partial=best['iou']>=.30 and best['containment']>=.75 and best['center_error']<=.20
    reliable = best['clean_mask']and camera['silhouette_iou'] >= .65 and (best['iou'] >= .45 or partial) and margin >= .10
    return {'status': 'matched' if reliable else 'needs_confirmation',
            'candidate_id': best['id'], 'visible_mask_iou': best['iou'], 'instance_margin': margin,
            'camera_silhouette_iou': camera['silhouette_iou'],
            'projected_support_containment':best['containment'],'projected_core_area_retained':retained,
            'partial_surface_support':partial and best['iou']<.45,
            'mask_quality':best['mask_quality'],
            'reason': '原图位置与可见轮廓对应' if reliable else '位置或轮廓证据不足，未自动指定参考',
            'scores_are_not_accuracy': True,
            'ranking': [{k: row[k] for k in ('id', 'iou', 'detection','clean_mask')} for row in rows]}, target


def alpha_polygon(path, crop=None, minimum_area=100):
    from PIL import Image
    image = Image.open(path).convert('RGBA')
    mask = np.asarray(image.getchannel('A')) > 128
    filled=binary_fill_holes(mask)
    if (filled&~mask).sum()/max(filled.sum(),1)>.06:raise ValueError('参考掩码含较大缺口，不能作为完整部件轮廓')
    mask=cv2.GaussianBlur(mask.astype('float32'),(0,0),.8)>.5
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours: raise ValueError('部件参考轮廓为空')
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < minimum_area: raise ValueError('部件参考轮廓过小')
    contour = cv2.approxPolyDP(contour, max(1.,max(mask.shape)*.006), True)[:, 0].astype(float)
    if crop is not None: contour += np.asarray(crop[:2])
    return contour


def unproject_to_plane(pixels, matrix, center, axes):
    matrix = np.asarray(matrix); output = []
    c = matrix@np.r_[center, 1.]
    x = matrix[:, :3]@axes[:, 0]; y = matrix[:, :3]@axes[:, 1]
    for u, v in pixels:
        a = np.array([[x[0]-u*x[2], y[0]-u*y[2]], [x[1]-v*x[2], y[1]-v*y[2]]])
        b = np.array([u*c[2]-c[0], v*c[2]-c[1]])
        if np.linalg.cond(a) > 1000: raise ValueError('参考视角过于侧向，不能可靠恢复部件轮廓')
        output.append(np.linalg.solve(a, b))
    return np.asarray(output)


def constrain_to_photo_rays(mesh,matrix,center,axes,maximum_shift):
    """Keep reconstructed front/back depth while respecting the photo outline.

    Both surfaces are constrained by the same image, so silhouette agreement
    here is an optimization objective, not independent shape validation.
    """
    matrix=np.asarray(matrix);local=(mesh.vertices-center)@axes
    footprint=center+local[:,:2]@axes[:,:2].T
    pixels,_=project(footprint,matrix)
    shifted=center+local[:,2:3]*axes[:,2]
    homogeneous=np.c_[shifted,np.ones(len(shifted))]@matrix.T
    x=matrix[:,:3]@axes[:,0];y=matrix[:,:3]@axes[:,1]
    u,v=pixels.T
    a=np.stack([np.c_[x[0]-u*x[2],y[0]-u*y[2]],np.c_[x[1]-v*x[2],y[1]-v*y[2]]],axis=1)
    b=np.c_[u*homogeneous[:,2]-homogeneous[:,0],v*homogeneous[:,2]-homogeneous[:,1]]
    if np.max(np.linalg.cond(a))>1000:raise ValueError('部件侧向过强，无法稳定约束照片轮廓')
    coordinates=np.linalg.solve(a,b[:,:,None])[:,:,0]
    vertices=shifted+coordinates@axes[:,:2].T
    displacement=np.linalg.norm(vertices-mesh.vertices,axis=1)
    if displacement.max()>maximum_shift:raise ValueError('原图轮廓要求的三维移动过大，未自动变形')
    result=mesh.copy();result.vertices=vertices
    return result,{'method':'single_view_ray_constraint_with_observed_depth','maximum_displacement_source_units':float(displacement.max()),'same_reference_used_for_constraint_and_comparison':True,'hidden_shape_verified':False}
