"""Sensor platform for LMSCloud."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BASE_DOMAIN, DOMAIN
from .coordinator import LMSCloudCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up LMSCloud sensor entities."""
    coordinator: LMSCloudCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            LMSCloudBorrowedBooksSensor(coordinator, entry),
            LMSCloudOverdueBooksSensor(coordinator, entry),
            LMSCloudNextDueDateSensor(coordinator, entry),
            LMSCloudNextExtensionPossibleSensor(coordinator, entry),
            LMSCloudReadyHoldsSensor(coordinator, entry),
            LMSCloudFeesBalanceSensor(coordinator, entry),
        ]
    )


class LMSCloudBaseSensor(CoordinatorEntity[LMSCloudCoordinator], SensorEntity):
    """Base class for LMSCloud coordinator sensors."""

    _attr_has_entity_name = True
    _value_key: str

    def __init__(
        self,
        coordinator: LMSCloudCoordinator,
        entry: ConfigEntry,
        unique_suffix: str,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"LMSCloud {entry.data[CONF_USERNAME]}",
            "manufacturer": "LMSCloud",
            "model": entry.data[CONF_BASE_DOMAIN],
        }

    @property
    def native_value(self) -> Any:
        """Return sensor value from coordinator snapshot."""
        data = self.coordinator.data
        if not data:
            return None
        return data.get(self._value_key)


class LMSCloudBorrowedBooksSensor(LMSCloudBaseSensor):
    """Expose borrowed book count."""

    _attr_translation_key = "borrowed_books"
    _attr_icon = "mdi:book-open-variant"
    _value_key = "borrowed_count"

    def __init__(self, coordinator: LMSCloudCoordinator, entry: ConfigEntry) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, entry, "borrowed_books")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Include borrowed item details."""
        data = self.coordinator.data
        if not data:
            return None
        items = data.get("borrowed_items")
        if not isinstance(items, list):
            return None
        return {
            "items": items,
            "item_count": len(items),
        }


class LMSCloudOverdueBooksSensor(LMSCloudBaseSensor):
    """Expose overdue book count."""

    _attr_translation_key = "overdue_books"
    _attr_icon = "mdi:book-alert-outline"
    _value_key = "overdue_count"

    def __init__(self, coordinator: LMSCloudCoordinator, entry: ConfigEntry) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, entry, "overdue_books")


class LMSCloudNextDueDateSensor(LMSCloudBaseSensor):
    """Expose next due date."""

    _attr_translation_key = "next_due_date"
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _value_key = "next_due_date"

    def __init__(self, coordinator: LMSCloudCoordinator, entry: ConfigEntry) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, entry, "next_due_date")

    @property
    def native_value(self) -> datetime | None:
        """Return next due date if available."""
        value = super().native_value
        if isinstance(value, datetime):
            return value
        return None


class LMSCloudReadyHoldsSensor(LMSCloudBaseSensor):
    """Expose number of holds ready for pickup."""

    _attr_translation_key = "ready_holds"
    _attr_icon = "mdi:bookshelf"
    _value_key = "holds_ready_count"

    def __init__(self, coordinator: LMSCloudCoordinator, entry: ConfigEntry) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, entry, "ready_holds")


class LMSCloudNextExtensionPossibleSensor(LMSCloudBaseSensor):
    """Expose next date/time when a renewal becomes possible."""

    _attr_translation_key = "next_extension_possible"
    _attr_icon = "mdi:update"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _value_key = "next_extension_possible"

    def __init__(self, coordinator: LMSCloudCoordinator, entry: ConfigEntry) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, entry, "next_extension_possible")

    @property
    def native_value(self) -> datetime | None:
        """Return next extension possible datetime if available."""
        value = super().native_value
        if isinstance(value, datetime):
            return value
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Include renewal details per checked-out item."""
        data = self.coordinator.data
        if not data:
            return None
        items = data.get("next_extension_items")
        if not isinstance(items, list):
            return None
        return {
            "items": items,
            "item_count": len(items),
        }


class LMSCloudFeesBalanceSensor(LMSCloudBaseSensor):
    """Expose outstanding library fees balance."""

    _attr_translation_key = "fees_balance"
    _attr_icon = "mdi:cash-multiple"
    _value_key = "fees_balance"

    def __init__(self, coordinator: LMSCloudCoordinator, entry: ConfigEntry) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, entry, "fees_balance")
