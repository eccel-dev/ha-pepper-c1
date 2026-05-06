"""Testy config flow — formularz konfiguracji huba Pepper C1."""
from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest


class TestConfigFlowUser:
    def test_schema_has_async_step_user(self):
        from custom_components.pepper_c1.config_flow import PepperC1ConfigFlow

        assert hasattr(PepperC1ConfigFlow, "async_step_user")
        assert callable(PepperC1ConfigFlow.async_step_user)

    def test_flow_version_is_2(self):
        from custom_components.pepper_c1.config_flow import PepperC1ConfigFlow

        assert PepperC1ConfigFlow.VERSION == 2

    def test_domain_matches_manifest(self):
        manifest_path = os.path.join(
            os.path.dirname(__file__),
            "..", "custom_components", "pepper_c1", "manifest.json"
        )
        with open(manifest_path) as f:
            manifest = json.load(f)

        from custom_components.pepper_c1.const import DOMAIN
        assert manifest["domain"] == DOMAIN

    def test_manifest_has_requirements(self):
        manifest_path = os.path.join(
            os.path.dirname(__file__),
            "..", "custom_components", "pepper_c1", "manifest.json"
        )
        with open(manifest_path) as f:
            manifest = json.load(f)

        assert "requirements" in manifest
        reqs = manifest["requirements"]
        assert any("pepper-c1" in r for r in reqs), f"pepper-c1 nie w requirements: {reqs}"

    def test_manifest_requires_min_020(self):
        manifest_path = os.path.join(
            os.path.dirname(__file__),
            "..", "custom_components", "pepper_c1", "manifest.json"
        )
        with open(manifest_path) as f:
            manifest = json.load(f)

        reqs = manifest["requirements"]
        pepper_req = next(r for r in reqs if "pepper-c1" in r)
        assert "0.2" in pepper_req or ">=" in pepper_req

    def test_manifest_iot_class_local_push(self):
        manifest_path = os.path.join(
            os.path.dirname(__file__),
            "..", "custom_components", "pepper_c1", "manifest.json"
        )
        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest.get("iot_class") == "local_push"

    async def test_shows_form_without_input(self):
        from custom_components.pepper_c1.config_flow import PepperC1ConfigFlow

        flow = PepperC1ConfigFlow.__new__(PepperC1ConfigFlow)
        flow.hass = None
        result = await flow.async_step_user(None)
        assert result["type"] == "form"
        assert result["step_id"] == "user"

    async def test_error_when_port_in_use(self):
        from custom_components.pepper_c1.config_flow import PepperC1ConfigFlow

        flow = PepperC1ConfigFlow.__new__(PepperC1ConfigFlow)
        flow.hass = None

        with patch(
            "custom_components.pepper_c1.config_flow._check_port_available",
            new=AsyncMock(return_value=False),
        ):
            result = await flow.async_step_user({"server_port": 1234})

        assert result["type"] == "form"
        assert result["errors"]["base"] == "port_in_use"
