"""Conservative semantic sanity checks; fail closed on an obvious whole-object label."""
def validate_semantic_proposal(manifest):
    groups=manifest.get('operation',{}).get('groups',[])
    for group in groups:
        eigen=group.get('pca_eigenvalues',[])
        if group.get('kind')=='tabletop' and len(eigen)==3 and eigen[1]>0 and eigen[2]/eigen[1]>.45 and group.get('area_fraction_final',0)>.5:
            raise ValueError('“桌面”候选包含大块立体结构，未可靠区分桌面和支撑；原版本保留')
