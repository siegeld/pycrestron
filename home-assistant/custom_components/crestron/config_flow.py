"""Config flow for Crestron integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME

from .const import CONF_IP_ID, DOMAIN


class CrestronConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Crestron."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step — processor connection details."""
        errors = {}

        if user_input is not None:
            # Validate connection by attempting token fetch
            try:
                from pycrestron.auth import fetch_auth_token

                await fetch_auth_token(
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                # Parse IP ID — accept hex (0x1a) or decimal (26)
                ip_id_str = user_input[CONF_IP_ID]
                ip_id = int(ip_id_str, 0)
                user_input[CONF_IP_ID] = ip_id

                return self.async_create_entry(
                    title=f"Crestron {user_input[CONF_HOST]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_IP_ID, default="0x1a"): str,
                    vol.Optional(CONF_PORT, default=49200): int,
                    vol.Required(CONF_USERNAME, default="admin"): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
