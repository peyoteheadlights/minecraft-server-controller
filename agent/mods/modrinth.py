"""Modrinth API client.

Only Modrinth's official API is used as a mod and plugin source. Searches
and version lists are filtered by the server's own loaders (Fabric, Quilt,
Forge, NeoForge, or Paper and its relatives for plugins), read from the
server type's capabilities. Downloads go through the safe downloader
(agent/downloads.py) and are accepted only when:

  * the URL is https and its host is a Modrinth CDN host
  * the filename passes agent.security.paths.safe_filename with the .jar
    allow-list
  * the downloaded bytes match the SHA-512 (or SHA-1) that Modrinth
    published for that file

Nothing downloaded here is ever executed by the agent.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from .. import downloads
from ..security.paths import PathSafetyError, safe_filename

log = logging.getLogger("msc.modrinth")

ALLOWED_HOSTS = {"cdn.modrinth.com", "cdn-raw.modrinth.com", "api.modrinth.com"}
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024  # 300 MB ceiling for a single mod file


class ModrinthError(RuntimeError):
    pass


class ModrinthNotFound(ModrinthError):
    """Modrinth answered that the project or version does not exist."""


class ModrinthClient:
    def __init__(self, config):
        self.config = config
        self.base = config.mods.modrinth_api.rstrip("/")
        self.user_agent = config.mods.user_agent
        self._client: httpx.AsyncClient | None = None

    @property
    def loaders(self) -> tuple[str, ...]:
        """The Modrinth loaders that fit this server's type, read each time
        because a server's type can change."""
        server_type = getattr(self.config, "server_type", None)
        return tuple(server_type.modrinth_loaders) if server_type else ("fabric",)

    @property
    def project_kind(self) -> str:
        server_type = getattr(self.config, "server_type", None)
        return "plugin" if server_type and server_type.content == "plugins" else "mod"

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
            raise ModrinthError(
                "Couldn't reach Modrinth. Check the PC's internet connection and try again."
            ) from exc
        if response.status_code == 404:
            raise ModrinthNotFound("Modrinth doesn't have that.")
        if response.status_code == 429:
            raise ModrinthError(
                "Modrinth is busy and asked us to slow down. Try again in a minute."
            )
        if response.status_code >= 500:
            raise ModrinthError("Modrinth has a problem right now. Try again later.")
        if response.status_code >= 400:
            raise ModrinthError(f"Modrinth refused the request (error {response.status_code}).")
        try:
            return response.json()
        except ValueError as exc:
            raise ModrinthError("Modrinth sent an answer that couldn't be read.") from exc

    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        minecraft_version: str | None = None,
        loaders: tuple[str, ...] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        loaders = self.loaders if loaders is None else loaders
        facets: list[list[str]] = []
        if self.project_kind == "mod":
            facets.append(["project_type:mod"])
        if loaders:
            # Inside one list Modrinth reads the facets as "any of these".
            facets.append([f"categories:{loader}" for loader in loaders])
        if minecraft_version:
            facets.append([f"versions:{minecraft_version}"])
        _json = json

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
                    "page": f"https://modrinth.com/{self.page_kind(hit)}/{hit.get('slug')}",
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
            "page": f"https://modrinth.com/{self.page_kind(data)}/{data.get('slug')}",
        }

    def page_kind(self, project: dict[str, Any]) -> str:
        kind = str(project.get("project_type") or self.project_kind)
        return kind if kind in ("mod", "plugin", "modpack") else self.project_kind

    async def versions(
        self,
        id_or_slug: str,
        minecraft_version: str | None = None,
        loaders: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        _json = json
        loaders = self.loaders if loaders is None else loaders
        params: dict[str, Any] = {}
        if loaders:
            params["loaders"] = _json.dumps(list(loaders))
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
        loaders: tuple[str, ...] | None = None,
        allow_types: tuple[str, ...] = ("release", "beta", "alpha"),
    ) -> dict | None:
        versions = await self.versions(id_or_slug, minecraft_version, loaders)
        for release_type in allow_types:
            for version in versions:
                if version["release_type"] == release_type:
                    return version
        return versions[0] if versions else None

    # ------------------------------------------------------------------
    async def download(self, version: dict[str, Any]) -> tuple[bytes, str, str]:
        """Download and check a mod file. Returns (bytes, filename, sha256)."""
        file_info = version.get("file") or {}
        url = file_info.get("url")
        filename = file_info.get("filename")
        if not url or not filename:
            raise ModrinthError("This version on Modrinth has no file to download.")

        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ModrinthError(
                "This file isn't hosted on Modrinth's own servers, so it wasn't downloaded."
            )
        try:
            safe_filename(filename, {".jar"})
        except PathSafetyError as exc:
            raise ModrinthError(f"This file can't be used: {exc}") from exc
        if not file_info.get("sha512") and not file_info.get("sha1"):
            raise ModrinthError(
                "Modrinth published no checksum for this file, so it can't be checked "
                "and wasn't installed."
            )
        spec = downloads.FileSpec(
            url=url,
            name=filename,
            sha512=file_info.get("sha512"),
            sha1=None if file_info.get("sha512") else file_info.get("sha1"),
            size=int(file_info["size"]) if file_info.get("size") else None,
            allow_unverified=False,
            max_bytes=MAX_DOWNLOAD_BYTES,
        )
        try:
            data, fetched = await downloads.download_bytes(spec)
        except downloads.DownloadError as exc:
            raise ModrinthError(str(exc)) from exc
        if not data.startswith(b"PK"):
            raise ModrinthError(
                "The downloaded file isn't a mod (.jar) file, so it was thrown away."
            )
        return data, filename, fetched.sha256
