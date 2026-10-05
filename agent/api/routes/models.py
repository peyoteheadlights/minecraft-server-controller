"""Request bodies accepted by the API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    label: str = Field(default="", max_length=80)


class CommandRequest(BaseModel):
    command: str = Field(max_length=512)
    confirm: bool = False


class StopRequest(BaseModel):
    timeout: float | None = Field(default=None, ge=1, le=1800)
    force: bool = False


class BackupRequest(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    includes: list[str] | None = None
    note: str | None = Field(default=None, max_length=300)


class RestoreRequest(BaseModel):
    confirm: bool = False
    start_after: bool = False
    safety_backup: bool = True


class ModInstallRequest(BaseModel):
    project: str = Field(max_length=100)
    version_id: str | None = Field(default=None, max_length=64)
    allow_replace: bool = False
    install_dependencies: bool = False


class ModFileRequest(BaseModel):
    filename: str = Field(max_length=180)


class ModUpdateRequest(ModFileRequest):
    version_id: str | None = Field(default=None, max_length=64)


class ModRollbackRequest(BaseModel):
    mod_id: str = Field(max_length=80)
    archive_path: str = Field(max_length=500)


class ScheduleRequest(BaseModel):
    name: str = Field(max_length=80)
    task: str = Field(max_length=32)
    kind: str = Field(max_length=16)
    expr: str = Field(max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class SettingsRequest(BaseModel):
    updates: dict[str, Any]


class MaintenanceRequest(BaseModel):
    enabled: bool


class DependencyInstallRequest(BaseModel):
    mod_ids: list[str] | None = Field(default=None, max_length=50)


class TpsCommandRequest(BaseModel):
    command: str = Field(max_length=100, description='"auto", "off", or a Minecraft command')


class ServerAddRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    # The folder that already holds the Minecraft server. Checked by
    # agent.security.paths.check_server_folder before anything is saved.
    directory: str = Field(min_length=1, max_length=400)
    # The server jar inside that folder. Empty: fabric-server-launch.jar or
    # server.jar, whichever is there.
    jar: str = Field(default="", max_length=180)
    # What kind of server is in the folder. Empty: Fabric, as before
    # server types existed.
    type: str | None = Field(default=None, max_length=32)
    id: str | None = Field(default=None, max_length=64)
    # A palette id or "#RRGGBB". Empty: the next color no server uses.
    color: str | None = Field(default=None, max_length=16)


class ServerSettingsRequest(BaseModel):
    updates: dict[str, Any]


class ServerColorRequest(BaseModel):
    color: str = Field(max_length=16, description='A palette id such as "teal", or "#RRGGBB"')


class PreferencesRequest(BaseModel):
    mode: Literal["simple", "technical"] | None = None
    theme: Literal["system", "light", "dark", "graphite", "contrast"] | None = None


class RecommendationActionRequest(BaseModel):
    action: Literal["dismiss", "snooze", "restore"]


class VersionChangeRequest(BaseModel):
    # Empty: keep the type this server already is.
    type: str | None = Field(default=None, max_length=32)
    minecraft_version: str = Field(min_length=1, max_length=64)
    # The loader or build version, where the type picks one separately.
    loader_version: str | None = Field(default=None, max_length=64)
    confirm: bool = False
    start_after: bool = False


class CreateServerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    # The folder to create. Must be empty or not exist yet; checked by
    # agent.security.paths.check_new_server_folder.
    directory: str = Field(min_length=1, max_length=400)
    type: str = Field(max_length=32)
    minecraft_version: str = Field(min_length=1, max_length=64)
    loader_version: str | None = Field(default=None, max_length=64)
    memory_mb: int | None = Field(default=None, ge=512, le=65536)
    # A palette id or "#RRGGBB". Empty: the next color no server uses.
    color: str | None = Field(default=None, max_length=16)
    # True only when the person ticked the box themselves. The agent never
    # accepts Minecraft's rules on their behalf.
    eula_accepted: bool = False


class CrossplayRequest(BaseModel):
    enabled: bool
    # The UDP port Bedrock players use. Empty: the port manager picks a free one.
    port: int | None = Field(default=None, ge=1, le=65535)


class GameSettingsRequest(BaseModel):
    values: dict[str, Any] = Field(max_length=40)


class GameSettingsRawRequest(BaseModel):
    text: str = Field(max_length=256 * 1024)


class PlayerActionRequest(BaseModel):
    action: Literal["whitelist_add", "whitelist_remove", "op", "deop", "kick", "ban", "pardon"]
    name: str = Field(min_length=1, max_length=17)
    reason: str | None = Field(default=None, max_length=100)
    confirm: bool = False


class DuplicateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    directory: str = Field(min_length=1, max_length=400)
    world: Literal["copy", "fresh"]


class ModpackNewRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    directory: str = Field(min_length=1, max_length=400)
    memory_mb: int | None = Field(default=None, ge=512, le=65536)
    color: str | None = Field(default=None, max_length=16)
    # True only when the person ticked the box themselves.
    eula_accepted: bool = False


class ModpackIntoRequest(BaseModel):
    token: str = Field(min_length=32, max_length=32)
    confirm: bool = False
