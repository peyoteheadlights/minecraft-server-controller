"""Server types and what each one supports (its capabilities).

Every Java server type the app can run is defined here, once: whether it
takes mods, plugins or neither, which mod metadata it reads, which Modrinth
loaders fit it, where its versions come from, how it is launched, which TPS
commands it answers, and whether Bedrock players can join it through
Geyser. Screens, the comparison table, the mod manager, the console
parser, backups and the port manager read these capabilities. Nothing
outside this package checks ``if type == "fabric"``.

Descriptions shown to people (what a type is best for, how easy it is) are
in the dashboard's strings table under ``types.*``, keyed by the type id.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_TYPE = "fabric"  # every server that existed before server types


class UnknownServerType(ValueError):
    pass


@dataclass(frozen=True)
class ServerType:
    id: str
    name: str
    edition: str = "java"
    # What the server adds on: "mods", "plugins" or None (Vanilla).
    content: str | None = None
    # The folder those live in, inside the server folder.
    content_folder: str | None = None
    # The loaders a mod or plugin jar may declare for this server to load it
    # (see agent/mods/jarinfo.py for how a jar's loader is read).
    accepts: tuple[str, ...] = ()
    # Metadata files read from each jar.
    metadata_files: tuple[str, ...] = ()
    # Modrinth loader names to search and filter by. Empty: no Modrinth.
    modrinth_loaders: tuple[str, ...] = ()
    # The name of the loader or build the console reports, if any.
    loader_name: str | None = None
    # Whether a loader version is picked separately from the Minecraft one.
    picks_loader: bool = False
    # Whether the official source lists snapshots and pre-releases.
    snapshots: bool = False
    # "jar" (java -jar file) or "args_file" (java @libraries/.../win_args.txt).
    launch: str = "jar"
    # The jar the app downloads or the installer leaves, named by the app.
    jar: str = "server.jar"
    # Runs an installer once after downloading ("forge", "neoforge", "quilt").
    installer: str | None = None
    # Where the version list comes from, for the Technical view.
    version_source: str = ""
    version_host: str = ""
    # Checksum the source publishes for the server download, if any.
    checksum: str | None = None
    # Console commands that report the tick rate, tried in this order.
    tps_commands: tuple[str, ...] = ("tick query", "tps", "spark tps")
    # GeyserMC's download name for this platform, or None: no crossplay.
    geyser_platform: str | None = None
    # Folders a backup must hold besides the configured list.
    backup_extra: tuple[str, ...] = ()
    # Files and folders the server software itself consists of (moved aside
    # as a whole when the version or type changes).
    software_paths: tuple[str, ...] = ()
    # "easy", "medium" or "advanced": how much there is to learn.
    ease: str = "medium"
    takes_memory_limit: bool = True
    reports_speed: bool = True
    ports: tuple[tuple[str, str], ...] = (("tcp", "game"),)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def has_content(self) -> bool:
        return self.content is not None

    @property
    def modrinth(self) -> bool:
        return bool(self.modrinth_loaders)

    @property
    def crossplay(self) -> bool:
        return self.geyser_platform is not None

    def accepts_any(self, loaders: list[str] | tuple[str, ...]) -> bool:
        return any(loader in self.accepts for loader in loaders)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            has_content=self.has_content,
            modrinth=self.modrinth,
            crossplay=self.crossplay,
        )
        data.pop("extra", None)
        return data


TYPES: dict[str, ServerType] = {
    t.id: t
    for t in (
        ServerType(
            id="vanilla",
            name="Vanilla",
            snapshots=True,
            jar="server.jar",
            version_source="Mojang version list",
            version_host="piston-meta.mojang.com",
            checksum="sha1",
            tps_commands=("tick query",),
            software_paths=("server.jar", "libraries", "versions"),
            ease="easy",
        ),
        ServerType(
            id="fabric",
            name="Fabric",
            content="mods",
            content_folder="mods",
            accepts=("fabric",),
            metadata_files=("fabric.mod.json",),
            modrinth_loaders=("fabric",),
            loader_name="Fabric Loader",
            picks_loader=True,
            snapshots=True,
            jar="fabric-server-launch.jar",
            version_source="Fabric meta API",
            version_host="meta.fabricmc.net",
            geyser_platform="fabric",
            backup_extra=("mods", "config"),
            software_paths=(
                "fabric-server-launch.jar",
                "fabric-server-launcher.properties",
                "server.jar",
                ".fabric",
                "libraries",
                "versions",
            ),
            ease="easy",
        ),
        ServerType(
            id="quilt",
            name="Quilt",
            content="mods",
            content_folder="mods",
            # Quilt loads most Fabric mods as well as its own.
            accepts=("quilt", "fabric"),
            metadata_files=("quilt.mod.json", "fabric.mod.json"),
            modrinth_loaders=("quilt", "fabric"),
            loader_name="Quilt Loader",
            picks_loader=True,
            snapshots=True,
            jar="quilt-server-launch.jar",
            installer="quilt",
            version_source="Quilt meta API",
            version_host="meta.quiltmc.org",
            backup_extra=("mods", "config"),
            software_paths=(
                "quilt-server-launch.jar",
                "server.jar",
                ".quilt",
                "libraries",
                "versions",
            ),
            ease="medium",
        ),
        ServerType(
            id="forge",
            name="Forge",
            content="mods",
            content_folder="mods",
            accepts=("forge",),
            metadata_files=("META-INF/mods.toml",),
            modrinth_loaders=("forge",),
            loader_name="Forge",
            picks_loader=True,
            launch="args_file",
            jar="",
            installer="forge",
            version_source="Forge Maven",
            version_host="maven.minecraftforge.net",
            tps_commands=("forge tps", "tick query", "spark tps"),
            backup_extra=("mods", "config", "defaultconfigs"),
            software_paths=(
                "libraries",
                "run.bat",
                "run.sh",
                "user_jvm_args.txt",
                "forge-server.jar",
            ),
            ease="advanced",
        ),
        ServerType(
            id="neoforge",
            name="NeoForge",
            content="mods",
            content_folder="mods",
            accepts=("neoforge",),
            metadata_files=("META-INF/neoforge.mods.toml",),
            modrinth_loaders=("neoforge",),
            loader_name="NeoForge",
            picks_loader=True,
            launch="args_file",
            jar="",
            installer="neoforge",
            version_source="NeoForged Maven",
            version_host="maven.neoforged.net",
            tps_commands=("neoforge tps", "tick query", "spark tps"),
            geyser_platform="neoforge",
            backup_extra=("mods", "config", "defaultconfigs"),
            software_paths=("libraries", "run.bat", "run.sh", "user_jvm_args.txt"),
            ease="advanced",
        ),
        ServerType(
            id="paper",
            name="Paper",
            content="plugins",
            content_folder="plugins",
            accepts=("paper", "bukkit"),
            metadata_files=("paper-plugin.yml", "plugin.yml"),
            modrinth_loaders=("paper", "spigot", "bukkit"),
            loader_name="Paper",
            jar="paper.jar",
            version_source="PaperMC downloads API",
            version_host="fill.papermc.io",
            checksum="sha256",
            tps_commands=("tps",),
            geyser_platform="spigot",
            backup_extra=("plugins", "config"),
            software_paths=("paper.jar", "cache", "libraries", "versions"),
            ease="easy",
        ),
        ServerType(
            id="purpur",
            name="Purpur",
            content="plugins",
            content_folder="plugins",
            accepts=("paper", "bukkit"),
            metadata_files=("paper-plugin.yml", "plugin.yml"),
            modrinth_loaders=("purpur", "paper", "spigot", "bukkit"),
            loader_name="Purpur",
            jar="purpur.jar",
            version_source="Purpur downloads API",
            version_host="api.purpurmc.org",
            checksum="md5",
            tps_commands=("tps",),
            geyser_platform="spigot",
            backup_extra=("plugins", "config"),
            software_paths=("purpur.jar", "cache", "libraries", "versions"),
            ease="medium",
        ),
    )
}

# The comparison table's "Recommended for most people" row: the type this
# app supports best (mods, Modrinth, crossplay, and every tool here).
RECOMMENDED = "fabric"


def get(type_id: str | None) -> ServerType:
    """The type with this id. An empty id means the default (Fabric)."""
    key = (type_id or DEFAULT_TYPE).strip().lower()
    found = TYPES.get(key)
    if found is None:
        raise UnknownServerType(
            f"'{type_id}' is not a server type this app knows. Use one of: {', '.join(TYPES)}."
        )
    return found


def check(type_id: Any) -> str:
    """Return the type id if it is known, or raise UnknownServerType."""
    return get(str(type_id or "")).id


def catalog() -> list[dict[str, Any]]:
    """Every type with its capabilities, for the dashboard's table."""
    return [{**t.to_dict(), "recommended": t.id == RECOMMENDED} for t in TYPES.values()]


def detected_type(loader_name: str | None) -> str | None:
    """The type a console's loader line names, or None. Used to warn when
    the console disagrees with the configured type, never to change it."""
    names = {t.loader_name.lower(): t.id for t in TYPES.values() if t.loader_name}
    return names.get((loader_name or "").lower())
