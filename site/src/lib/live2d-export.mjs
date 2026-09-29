import { loadModelResources, validateManifest } from './live2d-resources.mjs';

const encoder = new TextEncoder();
const crcTable = Uint32Array.from({ length: 256 }, (_, n) => {
  for (let i = 0; i < 8; i++) n = (n >>> 1) ^ ((n & 1) ? 0xedb88320 : 0);
  return n >>> 0;
});
const yieldTask = () => new Promise(resolve => setTimeout(resolve, 0));

// ZIP STORE: textures are already compressed. Keep packing cancellable without
// an additional compression library or a second set of hosted model archives.
export async function createModelZip({ manifest, blobs }, { signal, onProgress = () => {} } = {}) {
  validateManifest(manifest);
  const readme = `Live2D runtime model / Live2D 运行时模型\n\nOpen / 入口: ${manifest.model}\nKeep the directory structure when extracting. / 解压时保留目录结构。\n\nFiles use the source defaults; viewer parameter edits are not included.\n文件使用资源默认参数；不包含预览器中的参数修改。\nUnity motion curves were converted with linear interpolation. Unsupported motions are not included.\nUnity 动作使用线性插值转换；不包含未支持的动作。\nThis is a runtime package, not a Cubism Editor project.\n这是运行时资源包，不是 Cubism Editor 工程文件。\n\nSee manifest.json for file sizes, SHA-256 checksums and conversion reports.\n文件大小、SHA-256 摘要和动作转换报告见 manifest.json。\n`;
  const files = manifest.resources.map(r => [r.file, blobs.get(r.file)]);
  for (const [name, blob] of files) if (!blob || blob.size !== manifest.resources.find(r => r.file === name).bytes)
    throw new Error(`Missing export resource: ${name}`);
  if (files.some(([name]) => ['manifest.json', 'README.txt'].includes(name))) throw new Error('Reserved export filename');
  // The archive contains the original files, so no hosted transport bundle is required.
  const { jsonBundle, ...exportManifest } = manifest;
  files.push(['manifest.json', new Blob([JSON.stringify(exportManifest, null, 2) + '\n'])], ['README.txt', new Blob([readme])]);
  const parts = [], central = [];
  const total = files.reduce((n, [, blob]) => n + blob.size, 0);
  let offset = 0, processed = 0;
  onProgress({ phase: 'packing', loaded: 0, total });
  for (const [name, blob] of files) {
    signal?.throwIfAborted();
    const filename = encoder.encode(name);
    if (filename.length > 65535 || blob.size > 0xffffffff) throw new Error('ZIP entry is too large');
    let crc = 0xffffffff;
    for (let start = 0; start < blob.size; start += 1024 * 1024) {
      const bytes = new Uint8Array(await blob.slice(start, start + 1024 * 1024).arrayBuffer());
      signal?.throwIfAborted();
      for (const byte of bytes) crc = (crc >>> 8) ^ crcTable[(crc ^ byte) & 255];
      processed += bytes.length;
      onProgress({ phase: 'packing', loaded: processed, total });
      await yieldTask();
    }
    signal?.throwIfAborted();
    crc = (crc ^ 0xffffffff) >>> 0;
    const local = new Uint8Array(30), header = new DataView(local.buffer);
    header.setUint32(0, 0x04034b50, true); header.setUint16(4, 20, true);
    header.setUint16(6, 0x800, true); header.setUint16(12, 33, true); // UTF-8, 1980-01-01
    header.setUint32(14, crc, true); header.setUint32(18, blob.size, true); header.setUint32(22, blob.size, true);
    header.setUint16(26, filename.length, true);
    const record = new Uint8Array(46), directory = new DataView(record.buffer);
    directory.setUint32(0, 0x02014b50, true); directory.setUint16(4, 20, true);
    record.set(local.subarray(4, 30), 6); directory.setUint32(42, offset, true);
    parts.push(local, filename, blob); central.push(record, filename);
    offset += local.length + filename.length + blob.size;
    if (offset > 0xffffffff) throw new Error('ZIP archive is too large');
  }
  const centralSize = central.reduce((n, p) => n + p.length, 0);
  const end = new Uint8Array(22), footer = new DataView(end.buffer);
  footer.setUint32(0, 0x06054b50, true); footer.setUint16(8, files.length, true); footer.setUint16(10, files.length, true);
  footer.setUint32(12, centralSize, true); footer.setUint32(16, offset, true);
  signal?.throwIfAborted();
  return new Blob([...parts, ...central, end], { type: 'application/zip' });
}

export async function exportModel(root, options = {}) {
  const resources = await loadModelResources(root, options);
  return createModelZip(resources, options);
}
