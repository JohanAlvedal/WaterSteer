"""Optional built-in actuation of the two physical DHW levers.

Only active when the user selects Mode ``active``. Rules:

* Commands are only sent when the lever's actual state differs (idempotent).
* Moving towards safety (unblocking, requesting extra hot water for recovery)
  happens immediately.
* Moving towards optimization (blocking) is rate limited to prevent cycling.
* Extra hot water is only switched off if WaterSteer switched it on, so a
  manual request by the user is respected.
* Leaving active mode, unloading or stopping Home Assistant releases every
  lever WaterSteer holds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from .decision import MODE_ACTIVE, ControlOutput

_LOGGER = logging.getLogger(__name__)

MIN_BLOCK_INTERVAL_SECONDS = 10 * 60
SUPPORTED_LEVER_DOMAINS = ("switch", "input_boolean")


@dataclass(frozen=True, slots=True)
class Lever:
    """One on/off entity and what its ON state means."""

    entity_id: str
    on_means_block: bool = True


@dataclass(frozen=True, slots=True)
class ActuatorReport:
    """Result of one actuation pass."""

    active: bool
    commands: tuple[str, ...]
    warnings: tuple[str, ...]


class DhwActuator:
    """Drive the block lever and the extra-hot-water lever."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the actuator."""
        self.hass = hass
        self.block_owned = False
        self.extra_owned = False
        self.last_block_change: float | None = None

    async def apply(
        self,
        *,
        now: float,
        mode: str,
        output: ControlOutput,
        block_lever: Lever | None,
        extra_lever: Lever | None,
    ) -> ActuatorReport:
        """Bring the levers in line with the output when mode is active."""
        if mode != MODE_ACTIVE:
            commands = await self.release(block_lever, extra_lever)
            return ActuatorReport(active=False, commands=commands, warnings=())

        commands: list[str] = []
        warnings: list[str] = []

        if block_lever is None and extra_lever is None:
            warnings.append("active_mode_without_control_entities")

        if block_lever is not None:
            actual = self._lever_on(block_lever)
            if actual is None:
                warnings.append("block_entity_unavailable")
            else:
                blocked = actual == block_lever.on_means_block
                if output.block and not blocked:
                    if (
                        self.last_block_change is None
                        or now - self.last_block_change >= MIN_BLOCK_INTERVAL_SECONDS
                    ):
                        if await self._set(block_lever, block=True):
                            commands.append("block")
                            self.block_owned = True
                            self.last_block_change = now
                        else:
                            warnings.append("block_command_failed")
                elif not output.block and blocked:
                    if await self._set(block_lever, block=False):
                        commands.append("unblock")
                        self.block_owned = False
                        self.last_block_change = now
                    else:
                        warnings.append("block_command_failed")
                elif output.block and blocked:
                    self.block_owned = True

        if extra_lever is not None:
            actual = self._lever_on(extra_lever)
            if actual is None:
                warnings.append("extra_hot_water_entity_unavailable")
            elif output.extra_hot_water and not actual:
                if await self._switch(extra_lever.entity_id, turn_on=True):
                    commands.append("extra_hot_water_on")
                    self.extra_owned = True
                else:
                    warnings.append("extra_hot_water_command_failed")
            elif not output.extra_hot_water and actual and self.extra_owned:
                if await self._switch(extra_lever.entity_id, turn_on=False):
                    commands.append("extra_hot_water_off")
                    self.extra_owned = False
                else:
                    warnings.append("extra_hot_water_command_failed")
            elif not actual:
                self.extra_owned = False

        return ActuatorReport(
            active=True,
            commands=tuple(commands),
            warnings=tuple(warnings),
        )

    async def release(
        self,
        block_lever: Lever | None,
        extra_lever: Lever | None,
    ) -> tuple[str, ...]:
        """Release every lever WaterSteer holds. Safe to call repeatedly."""
        commands: list[str] = []
        if self.block_owned and block_lever is not None:
            actual = self._lever_on(block_lever)
            if (
                actual is not None
                and actual == block_lever.on_means_block
                and await self._set(block_lever, block=False)
            ):
                commands.append("unblock")
            self.block_owned = False
        if self.extra_owned and extra_lever is not None:
            if self._lever_on(extra_lever) is True and await self._switch(
                extra_lever.entity_id, turn_on=False
            ):
                commands.append("extra_hot_water_off")
            self.extra_owned = False
        return tuple(commands)

    def _lever_on(self, lever: Lever) -> bool | None:
        state = self.hass.states.get(lever.entity_id)
        if state is None:
            return None
        if state.state == STATE_ON:
            return True
        if state.state == STATE_OFF:
            return False
        return None

    async def _set(self, lever: Lever, *, block: bool) -> bool:
        turn_on = block == lever.on_means_block
        return await self._switch(lever.entity_id, turn_on=turn_on)

    async def _switch(self, entity_id: str, *, turn_on: bool) -> bool:
        domain = entity_id.split(".", 1)[0]
        if domain not in SUPPORTED_LEVER_DOMAINS:
            _LOGGER.error("WaterSteer cannot control %s", entity_id)
            return False
        service = "turn_on" if turn_on else "turn_off"
        try:
            await self.hass.services.async_call(
                domain,
                service,
                {"entity_id": entity_id},
                blocking=True,
            )
        except Exception:  # noqa: BLE001 - any failure must not stop the loop
            _LOGGER.exception("WaterSteer failed to call %s.%s", domain, service)
            return False
        _LOGGER.info("WaterSteer %s %s", service, entity_id)
        return True

    def as_dict(self) -> dict[str, Any]:
        """Serialize ownership so a restart can still release levers."""
        return {
            "block_owned": self.block_owned,
            "extra_owned": self.extra_owned,
            "last_block_change": self.last_block_change,
        }

    def restore(self, data: dict[str, Any] | None) -> None:
        """Restore ownership state."""
        if not isinstance(data, dict):
            return
        self.block_owned = data.get("block_owned") is True
        self.extra_owned = data.get("extra_owned") is True
        value = data.get("last_block_change")
        self.last_block_change = (
            float(value)
            if isinstance(value, int | float) and not isinstance(value, bool)
            else None
        )
