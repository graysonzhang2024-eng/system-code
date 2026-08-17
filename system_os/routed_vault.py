"""Physical routing between the shared work vault and personal-only vault."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import config
from .entity import ValidationError
from .machine import detect_machine
from .vault import Vault


PERSONAL_CATEGORIES = frozenset({"生活", "人际"})


class RoutedVault:
    """Vault-compatible facade with fail-closed personal-category routing.

    Existing records stay where they are. That avoids silently migrating real
    history; migration is a separate backed-up operation requiring approval.
    """

    def __init__(self) -> None:
        self.work = Vault(config.work_vault_path())
        self.routing_enabled = config.get_choice(
            "PERSONAL_VAULT_ROUTING", {"enabled", "disabled"}, "disabled"
        ) == "enabled"
        configured_personal = config.get_value("PERSONAL_VAULT_PATH").strip()
        self.personal = Vault(Path(configured_personal).expanduser()) if configured_personal else None

    def _readable(self) -> tuple[Vault, ...]:
        if (self.routing_enabled and detect_machine() == "personal"
                and self.personal is not None):
            return self.personal, self.work
        return (self.work,)

    def _owner(self, entity_id: str) -> Vault | None:
        for vault in self._readable():
            if vault.exists(entity_id):
                return vault
        return None

    def _target_for_create(self, meta: dict[str, Any]) -> Vault:
        parent_owner = None
        for key in ("knowledge_ref", "task_ref"):
            if meta.get(key):
                parent_owner = self._owner(str(meta[key]))
                break
        personal = (
            meta.get("category") in PERSONAL_CATEGORIES
            or parent_owner is self.personal
            or (meta.get("kind") == "daily" and detect_machine() == "personal")
        )
        if not self.routing_enabled:
            return self.work
        if personal and detect_machine() == "work":
            raise ValidationError("工作机拒绝创建生活/人际记录；请在个人机写入 personal-vault")
        if personal:
            if self.personal is None:
                raise ValidationError("PERSONAL_VAULT_PATH 未配置，个人记录已拒绝写入共享仓")
            if self.personal.root.resolve() == self.work.root.resolve():
                raise ValidationError("personal-vault 与 work-vault 不能指向同一目录")
            return self.personal
        return self.work

    def create(
        self, entity_id: str, meta: dict[str, Any] | None = None,
        body: str = "", *, overwrite: bool = False,
    ) -> dict[str, Any]:
        if self._owner(entity_id) is not None and not overwrite:
            raise ValidationError(f"记录已存在:{entity_id}(如需覆盖请传 overwrite=True)")
        return self._target_for_create(meta or {}).create(
            entity_id, meta, body, overwrite=overwrite
        )

    def read(self, entity_id: str) -> dict[str, Any]:
        owner = self._owner(entity_id)
        if owner is None:
            raise FileNotFoundError(f"记录不存在:{entity_id}")
        return owner.read(entity_id)

    def update(
        self, entity_id: str, meta_patch: dict[str, Any] | None = None,
        body: str | None = None,
    ) -> dict[str, Any]:
        owner = self._owner(entity_id)
        if owner is None:
            raise FileNotFoundError(f"记录不存在:{entity_id}")
        if (self.routing_enabled and owner is self.work and meta_patch
                and meta_patch.get("category") in PERSONAL_CATEGORIES):
            raise ValidationError("现有共享记录改为个人域需要走备份迁移流程")
        return owner.update(entity_id, meta_patch, body)

    def delete(self, entity_id: str) -> None:
        owner = self._owner(entity_id)
        if owner is None:
            raise FileNotFoundError(f"记录不存在,无法删除:{entity_id}")
        owner.delete(entity_id)

    def list(self, where: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        seen: set[str] = set()
        for vault in self._readable():
            for record in vault.list(where=where):
                entity_id = str(record["meta"].get("id", ""))
                if entity_id and entity_id not in seen:
                    seen.add(entity_id)
                    yield record

    def exists(self, entity_id: str) -> bool:
        return self._owner(entity_id) is not None
