export const DEFAULT_TILE_WIDTH = 160;
export const DEFAULT_TILE_HEIGHT = 80;


export function globalTileToLocal(tileIndex, gridWidth, anchorTileIndex) {
  if (
    !Number.isInteger(tileIndex) ||
    !Number.isInteger(gridWidth) ||
    gridWidth <= 0 ||
    !Number.isInteger(anchorTileIndex)
  ) throw new TypeError("tile conversion requires integer indexes and a positive grid width");
  return {
    x: tileIndex % gridWidth - anchorTileIndex % gridWidth,
    y: Math.floor(anchorTileIndex / gridWidth) - Math.floor(tileIndex / gridWidth),
  };
}


export function tileToWorld(
  x,
  y,
  { tileWidth = DEFAULT_TILE_WIDTH, tileHeight = DEFAULT_TILE_HEIGHT } = {},
) {
  return {
    x: (x - y) * tileWidth / 2,
    y: (x + y) * tileHeight / 2,
  };
}


export function worldToTile(
  point,
  { tileWidth = DEFAULT_TILE_WIDTH, tileHeight = DEFAULT_TILE_HEIGHT } = {},
) {
  const horizontal = point.x / (tileWidth / 2);
  const vertical = point.y / (tileHeight / 2);
  return {
    x: Math.round((horizontal + vertical) / 2),
    y: Math.round((vertical - horizontal) / 2),
  };
}


export function footprintPolygon(
  width,
  height,
  geometry,
) {
  const top = tileToWorld(0, 0, geometry);
  const right = tileToWorld(width, 0, geometry);
  const bottom = tileToWorld(width, height, geometry);
  const left = tileToWorld(0, height, geometry);
  const halfWidth = (geometry?.tileWidth ?? DEFAULT_TILE_WIDTH) / 2;
  return [
    top.x + halfWidth, top.y,
    right.x + halfWidth, right.y,
    bottom.x + halfWidth, bottom.y,
    left.x + halfWidth, left.y,
  ];
}


export function depthForFootprint(position, footprint = { width: 1, height: 1 }) {
  return position.x + position.y + footprint.width + footprint.height;
}
