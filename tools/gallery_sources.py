"""Gallery domains and exact catalog bindings; Stamp and Degree are distinct."""
TABLES = {'comics': 'MasterLoadingComics', 'stamps': 'MasterStamp', 'stickers': 'MasterDegree', 'backgrounds': 'MasterBackground'}


def asset_reference(kind, row):
    if kind == 'comics':
        return f"Image/Comic/{row['_imageAsset']}"
    return row[{'stamps': '_stampAsset', 'stickers': '_imagePath', 'backgrounds': '_assetPath'}[kind]]


def resolve_texture(locations, reference):
    matches = [loc for loc in locations if loc.primary_key == reference and loc.resource_type == 'UnityEngine.Texture2D']
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f'Ambiguous texture: {reference}')
    texture = matches[0]
    bundles = [loc for loc in locations if loc.primary_key in texture.dependencies and loc.primary_key.endswith('.bundle')]
    if len(bundles) != 1:
        raise ValueError(f'Ambiguous texture bundle: {reference}')
    return texture, bundles[0]
