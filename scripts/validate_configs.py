#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


REQUIRED_PROFILE_FIELDS = {
    "id",
    "name",
    "author",
    "version",
    "summary",
    "target_socs",
    "brands",
    "android_range",
    "module_version",
    "tags",
    "download_url",
    "sha256",
    "updated_at",
}

REQUIRED_METADATA_FIELDS = {
    "id",
    "name",
    "author",
    "version",
    "summary",
    "target_socs",
    "tested_devices",
    "module_version",
    "created_at",
}


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    index_path = repo_root / "index.json"
    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    if not isinstance(index_data.get("schema_version"), int):
        errors.append("index.json: schema_version 必须是整数")
    if not isinstance(index_data.get("generated_at"), str):
        errors.append("index.json: generated_at 必须是字符串")
    elif not is_iso8601(index_data["generated_at"]):
        errors.append("index.json: generated_at 必须是合法 ISO 8601 时间")

    profiles = index_data.get("profiles")
    if not isinstance(profiles, list):
        errors.append("index.json: profiles 必须是数组")
        profiles = []

    seen_ids: set[str] = set()
    seen_download_urls: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            errors.append("index.json: profiles[] 必须全部是对象")
            continue
        validate_profile(profile, repo_root, seen_ids, seen_download_urls, errors)

    if errors:
        print("validation failed", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("validation passed")
    return 0


def validate_profile(
    profile: dict,
    repo_root: Path,
    seen_ids: set[str],
    seen_download_urls: set[str],
    errors: list[str],
) -> None:
    missing_fields = sorted(REQUIRED_PROFILE_FIELDS - profile.keys())
    if missing_fields:
        errors.append(
            f"profile<{profile.get('id', 'unknown')}> 缺少字段: {', '.join(missing_fields)}"
        )
        return

    profile_id = profile["id"]
    if profile_id in seen_ids:
        errors.append(f"profile<{profile_id}> 重复")
    seen_ids.add(profile_id)

    download_url = profile["download_url"]
    if download_url in seen_download_urls:
        errors.append(f"profile<{profile_id}> download_url 重复: {download_url}")
    seen_download_urls.add(download_url)

    if not is_iso8601(profile["updated_at"]):
        errors.append(f"profile<{profile_id}> updated_at 必须是合法 ISO 8601 时间")

    package_path = resolve_package_path(profile["download_url"], repo_root)
    if package_path is None:
        errors.append(
            f"profile<{profile_id}> download_url 不是当前仓库 packages 目录下的 raw GitHub 地址"
        )
        return
    expected_package_name = f"{profile_id}.zip"
    if package_path.name != expected_package_name:
        errors.append(
            f"profile<{profile_id}> zip 文件名必须为 {expected_package_name}，当前为 {package_path.name}"
        )
    if not package_path.exists():
        errors.append(f"profile<{profile_id}> 缺少 zip 文件: {package_path.relative_to(repo_root)}")
        return

    actual_sha = sha256_file(package_path)
    if actual_sha != profile["sha256"]:
        errors.append(
            f"profile<{profile_id}> sha256 不匹配，index={profile['sha256']} actual={actual_sha}"
        )

    validate_zip(profile, package_path, errors)


def validate_zip(profile: dict, package_path: Path, errors: list[str]) -> None:
    profile_id = profile["id"]
    with zipfile.ZipFile(package_path) as zip_file:
        names = set(zip_file.namelist())
        for required_name in ("metadata.json", "applist.conf"):
            if required_name not in names:
                errors.append(f"profile<{profile_id}> zip 缺少 {required_name}")

        if "metadata.json" not in names:
            return

        metadata = json.loads(zip_file.read("metadata.json").decode("utf-8"))
        missing_metadata_fields = sorted(REQUIRED_METADATA_FIELDS - metadata.keys())
        if missing_metadata_fields:
            errors.append(
                f"profile<{profile_id}> metadata.json 缺少字段: {', '.join(missing_metadata_fields)}"
            )
        if metadata.get("id") != profile_id:
            errors.append(
                f"profile<{profile_id}> metadata.json 的 id ({metadata.get('id')}) 与 index.json 不一致"
            )
        if metadata.get("version") != profile["version"]:
            errors.append(
                f"profile<{profile_id}> metadata.json 的 version ({metadata.get('version')}) 与 index.json 不一致"
            )
        if metadata.get("module_version") != profile["module_version"]:
            errors.append(
                f"profile<{profile_id}> metadata.json 的 module_version ({metadata.get('module_version')}) 与 index.json 不一致"
            )
        if not is_iso8601(metadata.get("created_at", "")):
            errors.append(
                f"profile<{profile_id}> metadata.json 的 created_at 必须是合法 ISO 8601 时间"
            )


def resolve_package_path(download_url: str, repo_root: Path) -> Path | None:
    parsed = urlparse(download_url)
    if parsed.netloc != "raw.githubusercontent.com":
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 4:
        return None

    package_parts = path_parts[3:]
    if not package_parts or package_parts[0] != "packages":
        return None

    return repo_root.joinpath(*package_parts)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_iso8601(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False

    normalized = value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
