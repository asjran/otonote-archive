#!/usr/bin/env python3
import collections
import datetime as dt
import json
import os
import re
import struct
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = ROOT / "input/global/apks/2026-09-22-v1.0.1-25/base.apk"
UNPACKED = ROOT / "analysis" / ".work" / "base-apk"
OUT_DIR = ROOT / "analysis"
REPORT_MD = OUT_DIR / "ournotes_package_report.md"
REPORT_JSON = OUT_DIR / "ournotes_package_report.json"


def report_path(path):
    relative = path.relative_to(UNPACKED).as_posix()
    return f"{ZIP_PATH.relative_to(ROOT).as_posix()}!/{relative}"


ANDROID_ATTRS = {
    0x01010000: "theme",
    0x01010001: "label",
    0x01010002: "icon",
    0x01010003: "name",
    0x01010006: "permission",
    0x0101000F: "debuggable",
    0x01010010: "exported",
    0x01010011: "process",
    0x01010015: "allowBackup",
    0x0101001B: "versionCode",
    0x0101001C: "versionName",
    0x0101020C: "minSdkVersion",
    0x0101020D: "targetSdkVersion",
    0x0101021B: "screenOrientation",
    0x0101021C: "configChanges",
    0x01010226: "usesCleartextTraffic",
    0x01010232: "authorities",
    0x0101026C: "hardwareAccelerated",
    0x0101027F: "largeHeap",
    0x01010282: "supportsRtl",
    0x0101028C: "roundIcon",
    0x010103C1: "appCategory",
    0x0101046E: "extractNativeLibs",
    0x01010481: "requestLegacyExternalStorage",
    0x01010557: "compileSdkVersion",
    0x01010558: "compileSdkVersionCodename",
}


def read_u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def read_u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def decode_length8(buf, off):
    first = buf[off]
    if first & 0x80:
        return ((first & 0x7F) << 8) | buf[off + 1], off + 2
    return first, off + 1


def decode_length16(buf, off):
    first = read_u16(buf, off)
    if first & 0x8000:
        return ((first & 0x7FFF) << 16) | read_u16(buf, off + 2), off + 4
    return first, off + 2


def parse_string_pool(buf, off):
    chunk_type = read_u16(buf, off)
    if chunk_type != 0x0001:
        raise ValueError(f"expected string pool at 0x{off:x}, got 0x{chunk_type:x}")
    header_size = read_u16(buf, off + 2)
    chunk_size = read_u32(buf, off + 4)
    string_count = read_u32(buf, off + 8)
    flags = read_u32(buf, off + 16)
    strings_start = read_u32(buf, off + 20)
    is_utf8 = bool(flags & 0x100)
    strings = []
    for i in range(string_count):
        rel = read_u32(buf, off + header_size + i * 4)
        pos = off + strings_start + rel
        if is_utf8:
            _, pos = decode_length8(buf, pos)
            byte_len, pos = decode_length8(buf, pos)
            raw = buf[pos : pos + byte_len]
            strings.append(raw.decode("utf-8", "replace"))
        else:
            char_len, pos = decode_length16(buf, pos)
            raw = buf[pos : pos + char_len * 2]
            strings.append(raw.decode("utf-16le", "replace"))
    return strings, off + chunk_size


def typed_value_to_text(data_type, data, strings):
    if data_type == 0x03:
        return strings[data] if 0 <= data < len(strings) else f"@string_index/{data}"
    if data_type == 0x10:
        return str(struct.unpack("<i", struct.pack("<I", data))[0])
    if data_type == 0x11:
        return hex(data)
    if data_type == 0x12:
        return "true" if data else "false"
    if data_type == 0x01:
        return f"@0x{data:08x}"
    if data_type == 0x02:
        return f"?0x{data:08x}"
    if 0x1C <= data_type <= 0x1F:
        return f"#{data:08x}"
    return str(data)


def parse_axml(path):
    buf = path.read_bytes()
    if read_u16(buf, 0) != 0x0003:
        return {"error": "not Android binary XML"}
    off = read_u16(buf, 2)
    strings, off = parse_string_pool(buf, off)
    resource_ids = []
    events = []
    stack = []
    while off + 8 <= len(buf):
        chunk_type = read_u16(buf, off)
        header_size = read_u16(buf, off + 2)
        chunk_size = read_u32(buf, off + 4)
        if chunk_size <= 0:
            break
        if chunk_type == 0x0180:
            count = (chunk_size - header_size) // 4
            resource_ids = [read_u32(buf, off + header_size + i * 4) for i in range(count)]
        elif chunk_type == 0x0102:
            name_idx = read_u32(buf, off + 20)
            name = strings[name_idx] if name_idx < len(strings) else f"idx_{name_idx}"
            attr_start = read_u16(buf, off + 24)
            attr_size = read_u16(buf, off + 26)
            attr_count = read_u16(buf, off + 28)
            attrs = {}
            for i in range(attr_count):
                aoff = off + 16 + attr_start + i * attr_size
                ns_idx = read_u32(buf, aoff)
                attr_name_idx = read_u32(buf, aoff + 4)
                raw_value_idx = read_u32(buf, aoff + 8)
                data_type = buf[aoff + 15]
                data = read_u32(buf, aoff + 16)
                attr_name = strings[attr_name_idx] if attr_name_idx < len(strings) else None
                if not attr_name and i < len(resource_ids):
                    attr_name = ANDROID_ATTRS.get(resource_ids[i], f"res_0x{resource_ids[i]:08x}")
                elif attr_name_idx == 0xFFFFFFFF and i < len(resource_ids):
                    attr_name = ANDROID_ATTRS.get(resource_ids[i], f"res_0x{resource_ids[i]:08x}")
                if raw_value_idx != 0xFFFFFFFF and raw_value_idx < len(strings):
                    value = strings[raw_value_idx]
                else:
                    value = typed_value_to_text(data_type, data, strings)
                if ns_idx != 0xFFFFFFFF and ns_idx < len(strings) and strings[ns_idx].endswith("/android"):
                    attr_name = f"android:{attr_name}"
                attrs[attr_name or f"attr_{i}"] = value
            events.append({"tag": name, "depth": len(stack), "attrs": attrs})
            stack.append(name)
        elif chunk_type == 0x0103:
            if stack:
                stack.pop()
        off += chunk_size
    manifest_attrs = next((e["attrs"] for e in events if e["tag"] == "manifest"), {})
    application_attrs = next((e["attrs"] for e in events if e["tag"] == "application"), {})
    permissions = [
        e["attrs"].get("android:name") or e["attrs"].get("name")
        for e in events
        if e["tag"] in {"uses-permission", "uses-permission-sdk-23"}
    ]
    activities = [e["attrs"] for e in events if e["tag"] == "activity"]
    services = [e["attrs"] for e in events if e["tag"] == "service"]
    providers = [e["attrs"] for e in events if e["tag"] == "provider"]
    receivers = [e["attrs"] for e in events if e["tag"] == "receiver"]
    uses_sdk = [e["attrs"] for e in events if e["tag"] == "uses-sdk"]
    uses_features = [e["attrs"] for e in events if e["tag"] == "uses-feature"]
    return {
        "manifest": manifest_attrs,
        "application": application_attrs,
        "permissions": [p for p in permissions if p],
        "activities": activities,
        "services": services,
        "providers": providers,
        "receivers": receivers,
        "uses_sdk": uses_sdk,
        "uses_features": uses_features,
        "events": events,
    }


def file_magic(path, n=64):
    data = path.read_bytes()[:n]
    if data.startswith(b"UnityFS"):
        return "UnityFS"
    if data.startswith(b"dex\n"):
        return "Dalvik DEX"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"PK\x03\x04"):
        return "ZIP"
    if data[:2] == b"\x03\x00":
        return "Android binary XML"
    if data[:4] == b"\xfa\xb1\x1b\xaf":
        return "IL2CPP global metadata"
    return data[:16].hex()


def parse_unityfs_header(path):
    data = path.read_bytes()[:128]
    if not data.startswith(b"UnityFS\x00"):
        return None
    sig_end = data.index(b"\x00")
    format_version = struct.unpack_from(">I", data, sig_end + 1)[0]
    cursor = sig_end + 5
    target_end = data.index(b"\x00", cursor)
    target_version = data[cursor:target_end].decode("ascii", "replace")
    cursor = target_end + 1
    generator_end = data.index(b"\x00", cursor)
    generator_version = data[cursor:generator_end].decode("ascii", "replace")
    return {
        "signature": "UnityFS",
        "format_version": format_version,
        "unity_version": generator_version,
        "target_version": target_version,
    }


def png_size(path):
    data = path.read_bytes()[:32]
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    return struct.unpack(">II", data[16:24])


def strings_from_file(path, min_len=5):
    data = path.read_bytes()
    return [m.group(0).decode("utf-8", "ignore") for m in re.finditer(rb"[\x20-\x7e]{" + str(min_len).encode() + rb",}", data)]


def interesting_strings(strings):
    patterns = [
        r"https?://",
        r"Addressables?",
        r"AssetBundle",
        r"catalog",
        r"Download",
        r"Live2D",
        r"spine",
        r"Cri",
        r"Master",
        r"Gacha",
        r"MemberCard",
        r"Music",
        r"Character",
        r"Band/",
        r"Adv/",
        r"Resource",
        r"EncryptionToken",
    ]
    rx = re.compile("|".join(patterns), re.I)
    out = []
    seen = set()
    for s in strings:
        clean = s.strip()
        if clean in seen or len(clean) > 220:
            continue
        if rx.search(clean):
            seen.add(clean)
            out.append(clean)
        if len(out) >= 300:
            break
    return out


def main():
    OUT_DIR.mkdir(exist_ok=True)
    if not UNPACKED.exists():
        UNPACKED.mkdir(parents=True)
        with zipfile.ZipFile(ZIP_PATH) as zf:
            zf.extractall(UNPACKED)
    report = {"generated_at": dt.datetime.now().isoformat(timespec="seconds")}

    with zipfile.ZipFile(ZIP_PATH) as zf:
        infos = zf.infolist()
        report["zip"] = {
            "path": str(ZIP_PATH.relative_to(ROOT)),
            "compressed_size": ZIP_PATH.stat().st_size,
            "uncompressed_size": sum(i.file_size for i in infos),
            "file_count": len(infos),
            "top_files": [
                {"name": i.filename, "size": i.file_size, "compressed": i.compress_size}
                for i in sorted(infos, key=lambda x: x.file_size, reverse=True)[:30]
            ],
            "ext_counts": collections.Counter(Path(i.filename).suffix.lower() or "<none>" for i in infos),
            "dir_counts": collections.Counter((Path(i.filename).parts[0] if Path(i.filename).parts else "") for i in infos),
        }

    manifest_path = UNPACKED / "AndroidManifest.xml"
    report["manifest"] = parse_axml(manifest_path)

    important_paths = [
        UNPACKED / "classes.dex",
        UNPACKED / "classes2.dex",
        UNPACKED / "resources.arsc",
        UNPACKED / "assets/bin/Data/data.unity3d",
        UNPACKED / "assets/bin/Data/Managed/Metadata/global-metadata.dat",
        UNPACKED / "assets/bin/Data/boot.config",
        UNPACKED / "assets/bin/Data/ScriptingAssemblies.json",
        UNPACKED / "asset-delivery.properties",
        UNPACKED / "META-INF/com.android.games.engine.build_fingerprint",
    ]
    report["important_files"] = []
    for p in important_paths:
        if p.exists():
            item = {"path": report_path(p), "size": p.stat().st_size, "magic": file_magic(p)}
            if p.name == "data.unity3d":
                item["unityfs"] = parse_unityfs_header(p)
            if p.name == "global-metadata.dat":
                header = p.read_bytes()[:4].hex()
                item["first4_hex"] = header
                item["looks_plain_il2cpp_metadata"] = header == "fab11baf"
            report["important_files"].append(item)

    all_files = [p for p in UNPACKED.rglob("*") if p.is_file()]
    report["native_libs"] = [report_path(p) for p in all_files if p.suffix == ".so"]
    report["unity_like_files"] = [
        report_path(p)
        for p in all_files
        if p.suffix.lower() in {".unity3d", ".bundle", ".ab"} or "catalog" in p.name.lower()
    ]

    pngs = []
    for p in all_files:
        if p.suffix.lower() == ".png":
            size = png_size(p)
            pngs.append(
                {
                    "path": report_path(p),
                    "bytes": p.stat().st_size,
                    "width": size[0] if size else None,
                    "height": size[1] if size else None,
                }
            )
    report["pngs"] = sorted(pngs, key=lambda x: x["bytes"], reverse=True)

    script_json = UNPACKED / "assets/bin/Data/ScriptingAssemblies.json"
    if script_json.exists():
        report["scripting_assemblies"] = json.loads(script_json.read_text())

    text_sources = []
    for p in [
        UNPACKED / "assets/bin/Data/data.unity3d",
        UNPACKED / "assets/bin/Data/Managed/Metadata/global-metadata.dat",
        UNPACKED / "classes.dex",
        UNPACKED / "classes2.dex",
    ]:
        if p.exists():
            text_sources.extend(strings_from_file(p))
    report["interesting_strings"] = interesting_strings(text_sources)

    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = report["manifest"]
    mf = manifest.get("manifest", {})
    app = manifest.get("application", {})
    unity = next((i.get("unityfs") for i in report["important_files"] if i["path"].endswith("data.unity3d")), None)
    metadata = next((i for i in report["important_files"] if i["path"].endswith("global-metadata.dat")), None)
    lines = []
    lines.append("# アワーノーツ Package Static Report")
    lines.append("")
    lines.append(f"- Generated: {report['generated_at']}")
    lines.append(f"- Source package: `{ZIP_PATH.name}`")
    lines.append(f"- ZIP compressed size: {report['zip']['compressed_size']:,} bytes")
    lines.append(f"- ZIP uncompressed size: {report['zip']['uncompressed_size']:,} bytes")
    lines.append(f"- File count: {report['zip']['file_count']}")
    lines.append("")
    lines.append("## Android Manifest")
    for key in ["package", "android:versionCode", "android:versionName", "android:compileSdkVersion", "android:compileSdkVersionCodename", "android:requiredSplitTypes"]:
        if key in mf:
            lines.append(f"- {key}: `{mf[key]}`")
    for sdk in manifest.get("uses_sdk", []):
        parts = []
        if "android:minSdkVersion" in sdk:
            parts.append(f"minSdk={sdk['android:minSdkVersion']}")
        if "android:targetSdkVersion" in sdk:
            parts.append(f"targetSdk={sdk['android:targetSdkVersion']}")
        if parts:
            lines.append(f"- uses-sdk: `{', '.join(parts)}`")
    for key in ["android:name", "android:label", "android:theme", "android:debuggable", "android:allowBackup", "android:extractNativeLibs", "android:usesCleartextTraffic"]:
        if key in app:
            lines.append(f"- application {key}: `{app[key]}`")
    lines.append(f"- permissions: {len(manifest.get('permissions', []))}")
    for p in manifest.get("permissions", [])[:30]:
        lines.append(f"  - `{p}`")
    lines.append(f"- activities: {len(manifest.get('activities', []))}")
    for a in manifest.get("activities", [])[:20]:
        name = a.get("android:name") or a.get("name")
        if name:
            lines.append(f"  - `{name}` exported={a.get('android:exported', '')}")
    lines.append(f"- services: {len(manifest.get('services', []))}")
    for s in manifest.get("services", [])[:15]:
        name = s.get("android:name") or s.get("name")
        if name:
            lines.append(f"  - `{name}` exported={s.get('android:exported', '')}")
    lines.append(f"- providers: {len(manifest.get('providers', []))}")
    for p in manifest.get("providers", [])[:15]:
        name = p.get("android:name") or p.get("name")
        if name:
            lines.append(f"  - `{name}` authorities={p.get('android:authorities', '')}")
    lines.append(f"- receivers: {len(manifest.get('receivers', []))}")
    for r in manifest.get("receivers", [])[:15]:
        name = r.get("android:name") or r.get("name")
        if name:
            lines.append(f"  - `{name}` exported={r.get('android:exported', '')}")
    lines.append("")
    lines.append("## Unity / Game Runtime")
    if unity:
        lines.append(f"- UnityFS file: `assets/bin/Data/data.unity3d`")
        lines.append(f"- Unity version in bundle: `{unity.get('unity_version')}`")
        lines.append(f"- UnityFS format version: `{unity.get('format_version')}`")
    if metadata:
        lines.append(f"- IL2CPP metadata: `assets/bin/Data/Managed/Metadata/global-metadata.dat` ({metadata['size']:,} bytes)")
        lines.append(f"- Metadata first 4 bytes: `{metadata.get('first4_hex')}`")
        lines.append(f"- Plain Il2CppDumper metadata magic: `{metadata.get('looks_plain_il2cpp_metadata')}`")
    lines.append(f"- Native `.so` libraries found: {len(report['native_libs'])}")
    if not report["native_libs"]:
        lines.append("- No `libil2cpp.so` was present in this package; this looks like an incomplete base/split package for full IL2CPP dumping.")
    lines.append("")
    lines.append("## Important Files")
    for item in report["important_files"]:
        lines.append(f"- `{item['path']}`: {item['size']:,} bytes, {item['magic']}")
    lines.append("")
    lines.append("## Largest ZIP Entries")
    for item in report["zip"]["top_files"][:15]:
        lines.append(f"- `{item['name']}`: {item['size']:,} bytes")
    lines.append("")
    lines.append("## PNG Assets")
    lines.append(f"- PNG count: {len(report['pngs'])}")
    for p in report["pngs"][:25]:
        wh = f"{p['width']}x{p['height']}" if p["width"] else "unknown"
        lines.append(f"- `{p['path']}`: {p['bytes']:,} bytes, {wh}")
    lines.append("")
    lines.append("## Scripting Assemblies")
    assemblies = report.get("scripting_assemblies", {}).get("names", [])
    lines.append(f"- Assembly count: {len(assemblies)}")
    for name in assemblies[:80]:
        lines.append(f"- `{name}`")
    if len(assemblies) > 80:
        lines.append(f"- ... {len(assemblies) - 80} more in JSON report")
    lines.append("")
    lines.append("## Resource / Download Clues")
    for s in report["interesting_strings"][:120]:
        lines.append(f"- `{s}`")
    if len(report["interesting_strings"]) > 120:
        lines.append(f"- ... {len(report['interesting_strings']) - 120} more in JSON report")
    lines.append("")
    lines.append("## Practical Reading")
    lines.append("- This APK contains Unity startup data and metadata clues, but not the full runtime/native split.")
    lines.append("- The presence of Addressables/AssetBundle/Play Asset Delivery strings means most useful game resources are likely delivered outside this 22 MB APK.")
    lines.append("- For a full asset index, collect installed split APKs, asset packs, and post-launch downloaded cache from a device you are authorized to inspect.")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
