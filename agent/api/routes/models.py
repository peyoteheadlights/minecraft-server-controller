"""Request bodies accepted by the API."""

from __future__ import annotations

from typing import Any

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
