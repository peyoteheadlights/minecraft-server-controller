"""Modrinth API client.

Only Modrinth's official API is used as a mod source. Downloads are accepted
only when:

  * the URL is https and its host is a Modrinth CDN host
  * the filename passes agent.security.paths.safe_filename with the .jar
    allow-list
  * the downloaded bytes match the SHA-512 (and SHA-1 when present) that
    Modrinth published for that file

Nothing downloaded here is ever executed by the agent.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from ..security.paths import PathSafetyError, safe_filename

log = logging.getLogger("msc.modrinth")

ALLOWED_HOSTS = {"cdn.modrinth.com", "cdn-raw.modrinth.com", "api.modrinth.com"}
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024  # 300 MB ceiling for a single mod file


class ModrinthError(RuntimeError):
    pass


class ModrinthClient:
    def __init__(self, config):
        self.base = config.mods.modrinth_api.rstrip("/")
        self.user_agent = config.mods.user_agent
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> Any:
        client = await self._http()
        url = f"{self.base}{path}"
        try:
            response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ModrinthError(f"Modrinth is unreachable: {exc}") from exc
        if response.status_code == 404:
            raise ModrinthError("Not found on Modrinth")
        if response.status_code == 429:
            raise ModrinthError("Modrinth rate limit reached. Wait a minute and try again.")
        if response.status_code >= 400:
            raise ModrinthError(f"Modrinth returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise ModrinthError("Modrinth returned a response that could not be read") from exc

    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        minecraft_version: str | None = None,
        loader: str = "fabric",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        facets: list[list[str]] = [["project_type:mod"]]
        if loader:
            facets.append([f"categories:{loader}"])
        if minecraft_version:
            facets.append([f"versions:{minecraft_version}"])
        import json as _json

        data = await self._get(
            "/search",
            {
                "query": query or "",
                "limit": max(1, min(int(limit), 50)),
                "offset": max(0, int(offset)),
                "index": "relevance",
                "facets": _json.dumps(facets),
            },
        )
        hits = []
        for hit in data.get("hits", []):
            hits.append(
                {
                    "project_id": hit.get("project_id"),
                    "slug": hit.get("slug"),
                    "title": hit.get("title"),
                    "description": hit.get("description"),
                    "author": hit.get("author"),
                    "downloads": hit.get("downloads"),
                    "follows": hit.get("follows"),
                    "categories": hit.get("categories", []),
                    "versions": hit.get("versions", []),
                    "latest_version": hit.get("latest_version"),
                    "client_side": hit.get("client_side"),
                    "server_side": hit.get("server_side"),
                    "icon_url": hit.get("icon_url"),
                    "license": hit.get("license"),
                    "page": f"https://modrinth.com/mod/{hit.get('slug')}",
                }
            )
        return {
            "hits": hits,
            "total": data.get("total_hits", len(hits)),
            "offset": data.get("offset", 0),
        }

    async def project(self, id_or_slug: str) -> dict[str, Any]:
        data = await self._get(f"/project/{id_or_slug}")
        return {
            "project_id": data.get("id"),
            "slug": data.get("slug"),
            "title": data.get("title"),
            "description": data.get("description"),
            "body_short": (data.get("body") or "")[:1200],
            "categories": data.get("categories", []),
            "loaders": data.get("loaders", []),
            "game_versions": data.get("game_versions", []),
            "downloads": data.get("downloads"),
            "client_side": data.get("client_side"),
            "server_side": data.get("server_side"),
            "license": (data.get("license") or {}).get("id"),
            "icon_url": data.get("icon_url"),
            "page": f"https://modrinth.com/mod/{data.get('slug')}",
        }

    async def versions(
        self, id_or_slug: str, minecraft_version: str | None = None, loader: str = "fabric"
    ) -> list[dict[str, Any]]:
        import json as _json

        params: dict[str, Any] = {}
        if loader:
            params["loaders"] = _json.dumps([loader])
        if minecraft_version:
            params["game_versions"] = _json.dumps([minecraft_version])
        data = await self._get(f"/project/{id_or_slug}/version", params)
        return [self._version_summary(v) for v in data]

    async def version(self, version_id: str) -> dict[str, Any]:
        return self._version_summary(await self._get(f"/version/{version_id}"))

    @staticmethod
    def _version_summary(v: dict[str, Any]) -> dict[str, Any]:
        primary = None
        for file in v.get("files", []):
            if file.get("primary"):
                primary = file
                break
        if primary is None and v.get("files"):
            primary = v["files"][0]
        primary = primary or {}
        return {
            "version_id": v.get("id"),
            "project_id": v.get("project_id"),
            "name": v.get("name"),
            "version_number": v.get("version_number"),
            "release_type": v.get("version_type"),
            "game_versions": v.get("game_versions", []),
            "loaders": v.get("loaders", []),
            "downloads": v.get("downloads"),
            "date_published": v.get("date_published"),
            "changelog": (v.get("changelog") or "")[:1000],
            "dependencies": [
                {
                    "project_id": d.get("project_id"),
                    "version_id": d.get("version_id"),
                    "type": d.get("dependency_type"),
                }
                for d in v.get("dependencies", [])
            ],
            "file": {
                "filename": primary.get("filename"),
                "url": primary.get("url"),
                "size": primary.get("size"),
                "sha1": (primary.get("hashes") or {}).get("sha1"),
                "sha512": (primary.get("hashes") or {}).get("sha512"),
            },
        }

    async def latest_for(
        self,
        id_or_slug: str,
        minecraft_version: str | None,
        loader: str = "fabric",
        allow_types: tuple[str, ...] = ("release", "beta", "alpha"),
    ) -> dict | None:
        versions = await self.versions(id_or_slug, minecraft_version, loader)
        for release_type in allow_types:
            for version in versions:
                if version["release_type"] == release_type:
                    return version
        return versions[0] if versions else None

    # ------------------------------------------------------------------
    async def download(self, version: dict[str, Any]) -> tuple[bytes, str, str]:
        """Download and verify a mod file. Returns (bytes, filename, sha256)."""
        file_info = version.get("file") or {}
        url = file_info.get("url")
        filename = file_info.get("filename")
        if not url or not filename:
            raise ModrinthError("This Modrinth version has no downloadable file")

        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ModrinthError(f"Refusing to download from an unexpected host: {parsed.hostname}")
        try:
            safe_filename(filename, {".jar"})
        except PathSafetyError as exc:
            raise ModrinthError(f"Refusing this file: {exc}") from exc

        client = await self._http()
        payload = bytearray()
        try:
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise ModrinthError(f"Download failed with HTTP {response.status_code}")
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > MAX_DOWNLOAD_BYTES:
                        raise ModrinthError("The file is larger than the 300 MB limit")
        except httpx.HTTPError as exc:
            raise ModrinthError(f"Download failed: {exc}") from exc

        data = bytes(payload)
        expected_size = file_info.get("size")
        if expected_size and len(data) != int(expected_size):
            raise ModrinthError(
                f"Size mismatch: expected {expected_size} bytes, received {len(data)}"
            )
        sha512 = file_info.get("sha512")
        if sha512:
            actual = hashlib.sha512(data).hexdigest()
            if actual.lower() != str(sha512).lower():
                raise ModrinthError("SHA-512 checksum did not match. The download was discarded.")
        sha1 = file_info.get("sha1")
        if sha1:
            actual1 = hashlib.sha1(data).hexdigest()
            if actual1.lower() != str(sha1).lower():
                raise ModrinthError("SHA-1 checksum did not match. The download was discarded.")
        if not sha512 and not sha1:
            raise ModrinthError(
                "Modrinth published no checksum for this file, so it was not installed"
            )
        if not data.startswith(b"PK"):
            raise ModrinthError("The downloaded file is not a zip/jar archive")
        return data, filename, hashlib.sha256(data).hexdigest()
