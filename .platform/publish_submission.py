#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["publish", "unpublish"], default="publish")
    parser.add_argument("--export-json")
    parser.add_argument("--source-file")
    parser.add_argument("--profile-id")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--public-base-url", required=True)
    parser.add_argument("--module-version", default="1.6.3")
    parser.add_argument("--delete-package", default="true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    packages_dir = repo_root / "packages"
    index_path = repo_root / "index.json"

    packages_dir.mkdir(parents=True, exist_ok=True)
    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    profiles = index_data.get("profiles", [])

    if args.mode == "unpublish":
        if not args.profile_id:
            raise RuntimeError("--profile-id is required for unpublish")
        delete_package = str(args.delete_package).lower() not in {"0", "false", "no"}
        unpublish_profile(index_data, profiles, packages_dir, args.profile_id, delete_package)
        index_data["generated_at"] = now_iso()
        index_path.write_text(json.dumps(index_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0

    if not args.export_json or not args.source_file:
        raise RuntimeError("--export-json and --source-file are required for publish mode")

    export_data = json.loads(Path(args.export_json).read_text(encoding="utf-8"))
    source_file = Path(args.source_file).resolve()

    profile_id = export_data["suggested_profile_id"]
    package_path = packages_dir / f"{profile_id}.zip"
    timestamp = now_iso()

    existing = next((item for item in profiles if item.get("id") == profile_id), None)

    if export_data["source_kind"] == "conf":
        package_bytes = build_package_from_conf(export_data, source_file, existing, args.module_version, timestamp)
    elif export_data["source_kind"] == "zip":
        package_bytes = validate_existing_zip(source_file)
    else:
        raise RuntimeError(f"unsupported source_kind: {export_data['source_kind']}")

    package_path.write_bytes(package_bytes)

    metadata = read_zip_json(package_path, "metadata.json")
    profile = {
        "id": metadata["id"],
        "name": metadata["name"],
        "author": metadata["author"],
        "contact": export_data.get("contact", "").strip(),
        "version": metadata["version"],
        "summary": metadata["summary"],
        "target_socs": metadata.get("target_socs", []),
        "brands": existing.get("brands", []) if existing else [],
        "android_range": existing.get("android_range", {"min_api": 31, "max_api": 36}) if existing else {"min_api": 31, "max_api": 36},
        "module_version": metadata["module_version"],
        "tags": existing.get("tags", []) if existing else [],
        "download_url": f"{args.public_base_url.rstrip('/')}/packages/{package_path.name}",
        "sha256": sha256_bytes(package_bytes),
        "updated_at": timestamp,
    }

    updated_profiles = [item for item in profiles if item.get("id") != profile_id]
    updated_profiles.append(profile)
    updated_profiles.sort(key=lambda item: item["id"])
    index_data["profiles"] = updated_profiles
    index_data["generated_at"] = timestamp
    index_path.write_text(json.dumps(index_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


def unpublish_profile(index_data: dict, profiles: list[dict], packages_dir: Path, profile_id: str, delete_package: bool) -> None:
    existing = next((item for item in profiles if item.get("id") == profile_id), None)
    if not existing:
        raise RuntimeError(f"profile not found: {profile_id}")

    index_data["profiles"] = [item for item in profiles if item.get("id") != profile_id]

    if not delete_package:
        return

    candidates = {packages_dir / f"{profile_id}.zip"}
    download_url = existing.get("download_url", "")
    parsed = urlparse(download_url)
    if parsed.path:
        filename = Path(parsed.path).name
        if filename:
            candidates.add(packages_dir / filename)

    for package_path in candidates:
        if package_path.exists():
            package_path.unlink()


def build_package_from_conf(export_data: dict, source_file: Path, existing: dict | None, module_version: str, timestamp: str) -> bytes:
    with source_file.open("rb") as fh:
        conf_bytes = fh.read()

    version = bump_patch(existing.get("version")) if existing else "1.0.0"
    metadata = {
        "id": export_data["suggested_profile_id"],
        "name": export_data["title"],
        "author": export_data["author_name"],
        "contact": export_data.get("contact", "").strip(),
        "version": version,
        "summary": export_data["summary"],
        "target_socs": split_lines(export_data.get("target_socs", "")),
        "tested_devices": split_lines(export_data.get("devices", "")),
        "module_version": existing.get("module_version", module_version) if existing else module_version,
        "created_at": timestamp,
    }
    readme = build_readme(export_data)

    from io import BytesIO

    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        zf.writestr("applist.conf", conf_bytes)
        zf.writestr("README.md", readme)
    return output.getvalue()


def validate_existing_zip(source_file: Path) -> bytes:
    raw = source_file.read_bytes()
    with zipfile.ZipFile(source_file) as zf:
        names = set(zf.namelist())
        for required in ("metadata.json", "applist.conf"):
            if required not in names:
                raise RuntimeError(f"zip missing required file: {required}")
    return raw


def build_readme(export_data: dict) -> str:
    tuning_label = {
        "low": "省电",
        "medium": "平衡",
        "high": "性能",
    }.get(str(export_data.get("risk_level", "")).strip(), "平衡")
    lines = [
        f"# {export_data['title']}",
        "",
        export_data.get("summary", "").strip(),
        "",
        "## 投稿信息",
        "",
        f"- 作者：{export_data.get('author_name', '').strip()}",
        f"- 联系方式：{export_data.get('contact', '').strip() or '未填写'}",
        f"- SoC：{export_data.get('target_socs', '').strip()}",
        f"- 设备：{export_data.get('devices', '').strip()}",
        f"- Android：{export_data.get('android_versions', '').strip()}",
        f"- 配置倾向：{tuning_label}",
    ]
    notes = export_data.get("notes", "").strip()
    if notes:
        lines.extend(["", "## 说明", "", notes])
    review_notes = export_data.get("review_notes", "").strip()
    if review_notes:
        lines.extend(["", "## 审核备注", "", review_notes])
    return "\n".join(lines).rstrip() + "\n"


def read_zip_json(path: Path, name: str) -> dict:
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read(name).decode("utf-8"))


def split_lines(value: str) -> list[str]:
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def bump_patch(version: str | None) -> str:
    if not version:
        return "1.0.0"
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return version
    major, minor, patch = [int(part) for part in parts]
    return f"{major}.{minor}.{patch + 1}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
