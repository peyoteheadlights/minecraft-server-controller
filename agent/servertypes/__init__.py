"""Server types and what each one supports (its capabilities).

Every server type the app can run is defined here, once: the seven Java
types and Mojang's Bedrock Dedicated Server. For each: whether it
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
    # "jar" (java -jar file), "args_file" (java @libraries/.../win_args.txt)
    # or "exe" (the server's own program, run directly: Bedrock).
    launch: str = "jar"
    # The jar the app downloads or the installer leaves, named by the app.
    jar: str = "server.jar"
    # Runs an installer once after downloading ("forge", "neoforge", "quilt").
    installer: str | None = None
    # The installer's own arguments after "java -jar <installer>". Only
    # "{minecraft}" and "{loader}" are filled in, from versions the official
    # source listed (see install.installer_command).
    installer_args: tuple[str, ...] = ()
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
    # The key a Modrinth modpack (.mrpack) uses for this loader in its
    # "dependencies", and how its version is written as this app's loader
    # version. None: modpacks can't target this type.
    mrpack_dependency: str | None = None
    mrpack_loader_version: str = "{loader}"
    takes_memory_limit: bool = True
    reports_speed: bool = True
    # Whether the server runs on Java (so Java is checked before a start).
    needs_java: bool = True
    # The console's line format and the server's own files (player lists,
    # server.properties keys): "java" or "bedrock". Each module that reads
    # them keeps one set of patterns per dialect.
    dialect: str = "java"
    # Bedrock add-ons (.mcpack, .mcaddon), installed into behavior_packs and
    # resource_packs and switched on per world (agent/addons.py).
    addons: bool = False
    # Whether the console prints players' chat (Bedrock's doesn't), so the
    # Chat page can say reading it isn't available instead of looking empty.
    reads_chat: bool = True
    # Whether the server has a ban list (Bedrock has none).
    bans: bool = True
    # How a running server's world is copied for a backup: "save_off"
    # (save-all, save-off, copy, save-on) or "save_hold" (Bedrock's save
    # hold, save query, copy each file to its listed length, save resume).
    backup_method: str = "save_off"
    # The folder worlds live in, inside the server folder ("" for the
    # server folder itself), and the world name when level-name isn't set.
    world_root: str = ""
    default_level_name: str = "world"
    # Where a running server is checked as listening: "tcp" (a connect) or
    # "raknet" (Bedrock's unconnected ping over UDP).
    ping: str = "tcp"
    # The port a new server of this type starts looking from.
    default_port: int = 25565
    # True when the official source offers only the newest version, so
    # older ones exist only where this app kept a copy it downloaded.
    latest_only: bool = False
    # Terms the person ticks themselves before the first download, as
    # (name, link) pairs. Empty: Minecraft's EULA in eula.txt, as Java does.
    download_terms: tuple[tuple[str, str], ...] = ()
    # Bukkit's layout: the Nether and the End in their own folders beside
    # the world (world_nether/DIM-1, world_the_end/DIM1), where single-player
    # and every other type keep them inside it (world/DIM-1, world/DIM1).
    # World import and download convert between the two.
    split_dimensions: bool = False
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

    @property
    def game_protocol(self) -> str:
        """ "tcp" or "udp": what the server's game port is."""
        return self.ports[0][0]

    def can_change_to(self, other: ServerType) -> bool:
        """A version or type change keeps the world, so it stays within one
        edition: Java and Bedrock worlds are different formats."""
        return other.edition == self.edition

    def accepts_any(self, loaders: list[str] | tuple[str, ...]) -> bool:
        return any(loader in self.accepts for loader in loaders)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            has_content=self.has_content,
            modrinth=self.modrinth,
            crossplay=self.crossplay,
            game_protocol=self.game_protocol,
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
            mrpack_dependency="fabric-loader",
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
            # Quilt's installer: install server <minecraft> <loader>, into
            # the current folder, fetching Mojang's server jar as well.
            installer_args=(
                "install",
                "server",
                "{minecraft}",
                "{loader}",
                "--download-server",
                "--install-dir=.",
            ),
            version_source="Quilt meta API",
            version_host="meta.quiltmc.org",
            mrpack_dependency="quilt-loader",
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
            installer_args=("--installServer",),
            version_source="Forge Maven",
            version_host="maven.minecraftforge.net",
            tps_commands=("forge tps", "tick query", "spark tps"),
            # Forge's Maven names a build "<minecraft>-<build>"; a modpack
            # gives only the build.
            mrpack_dependency="forge",
            mrpack_loader_version="{minecraft}-{loader}",
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
            installer_args=("--installServer",),
            version_source="NeoForged Maven",
            version_host="maven.neoforged.net",
            tps_commands=("neoforge tps", "tick query", "spark tps"),
            geyser_platform="neoforge",
            mrpack_dependency="neoforge",
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
            split_dimensions=True,
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
            split_dimensions=True,
            ease="medium",
        ),
        ServerType(
            id="bedrock",
            name="Bedrock",
            edition="bedrock",
            launch="exe",
            # The program the download unpacks; it is run directly from the
            # server's folder (see docs/security.md).
            jar="bedrock_server.exe",
            version_source="Mojang's download links service",
            version_host="net-secondary.web.minecraft-services.net",
            tps_commands=(),
            backup_extra=("worlds", "allowlist.json", "permissions.json"),
            ease="easy",
            takes_memory_limit=False,
            reports_speed=False,
            needs_java=False,
            dialect="bedrock",
            addons=True,
            reads_chat=False,
            bans=False,
            backup_method="save_hold",
            world_root="worlds",
            default_level_name="Bedrock level",
            ping="raknet",
            default_port=19132,
            latest_only=True,
            download_terms=(
                ("eula", "https://www.minecraft.net/eula"),
                ("privacy", "https://go.microsoft.com/fwlink/?LinkId=521839"),
            ),
            # 19132 for IPv4 and 19133 for IPv6, both UDP.
            ports=(("udp", "game"), ("udp", "game_v6")),
        ),
    )
}
JAVA_TYPES = tuple(t for t in TYPES.values() if t.edition == "java")

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
    """Every type with its capabilities, for the dashboard's table. Each says
    its edition; the table shows one edition at a time."""
    return [{**t.to_dict(), "recommended": t.id == RECOMMENDED} for t in TYPES.values()]


def detected_type(loader_name: str | None) -> str | None:
    """The type a console's loader line names, or None. Used to warn when
    the console disagrees with the configured type, never to change it."""
    names = {t.loader_name.lower(): t.id for t in TYPES.values() if t.loader_name}
    return names.get((loader_name or "").lower())


def for_mrpack(dependencies: dict[str, Any]) -> tuple[ServerType, str | None]:
    """The type and loader version a modpack's "dependencies" ask for. A
    pack naming only Minecraft is Vanilla. Raises UnknownServerType for a
    loader this app can't run."""
    loaders = [key for key in dependencies if key != "minecraft"]
    if not loaders:
        return TYPES["vanilla"], None
    for server_type in TYPES.values():
        key = server_type.mrpack_dependency
        if key and key in dependencies:
            if len(loaders) > 1:
                break
            loader = server_type.mrpack_loader_version.format(
                minecraft=str(dependencies.get("minecraft") or ""),
                loader=str(dependencies[key]),
            )
            return server_type, loader
    raise UnknownServerType(
        "This modpack needs "
        + ", ".join(sorted(loaders))
        + ", which this app can't set up. It can set up packs for Fabric, Quilt, Forge "
        "and NeoForge."
    )
