"""honest-vies-mcp — MCP server for the EU VIES VAT number validation API.

Wraps the European Commission's VIES REST endpoint (https://ec.europa.eu/
taxation_customs/vies/rest-api/check-vat-number) — the authoritative source
for cross-border EU VAT number validation. No authentication, no
registration, no rate limit. Data flows only between your machine and the
Commission's servers.

Primary use case: a Polish JDG issuing a 0% VAT (reverse-charge) invoice to
an EU B2B counterparty must verify the counterparty's VAT number in VIES
BEFORE issuing the invoice — and keep evidence of the check. Passing a
`requester_country` + `requester_vat` returns a consultation number
(`requestIdentifier`) that serves as legally accepted proof of the check.

Tools: check_vat, list_supported_countries.

Author: Bartosz Kuć <firma@bartosza.pl>
Repo:   https://github.com/bartosz-kuc/honest-vies-mcp
License: MIT
"""

import asyncio
import json
import re
from typing import Any

import requests

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

VIES_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number"

# EU member states + XI (Northern Ireland, post-Brexit VAT scheme) + EL (Greece
# uses EL not GR in VIES). Codes below match VIES exactly.
SUPPORTED_COUNTRIES = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CY": "Cyprus",
    "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "EE": "Estonia",
    "EL": "Greece", "ES": "Spain", "FI": "Finland", "FR": "France",
    "HR": "Croatia", "HU": "Hungary", "IE": "Ireland", "IT": "Italy",
    "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "MT": "Malta",
    "NL": "Netherlands", "PL": "Poland", "PT": "Portugal", "RO": "Romania",
    "SE": "Sweden", "SI": "Slovenia", "SK": "Slovakia",
    "XI": "Northern Ireland (UK, post-Brexit VAT scheme)",
}

COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
# VIES VAT numbers are alphanumeric (some countries include letters, e.g. NL).
COMBINED_VAT_RE = re.compile(r"^([A-Z]{2})[- ]?([A-Z0-9]+)$")


def _clean_vat_number(raw: str) -> str:
    """Strip spaces, dashes, dots — VIES accepts only [A-Z0-9]."""
    cleaned = re.sub(r"[\s\-\.]", "", raw).upper()
    if not cleaned:
        raise ValueError(f"VAT number is empty after cleaning: {raw!r}")
    return cleaned


def _split_combined_vat(vat: str) -> tuple[str, str]:
    """Accept combined forms like 'PL5252344078' or 'PL 525-234-40-78'."""
    normalized = re.sub(r"[\s\-\.]", "", vat).upper()
    m = COMBINED_VAT_RE.match(normalized)
    if not m:
        raise ValueError(f"Cannot parse combined VAT {vat!r}. Expected format: 'PL1234567890' or provide country_code + vat_number separately.")
    return m.group(1), m.group(2)


def _validate_country(code: str) -> str:
    code = code.strip().upper()
    if not COUNTRY_RE.match(code):
        raise ValueError(f"Country code must be 2 uppercase letters, got {code!r}")
    if code not in SUPPORTED_COUNTRIES:
        raise ValueError(
            f"Country {code!r} is not in the VIES scheme. "
            f"Supported: {', '.join(sorted(SUPPORTED_COUNTRIES.keys()))}. "
            f"Note: Greece uses 'EL' not 'GR', and 'XI' is Northern Ireland."
        )
    return code


def _check_vat(country: str, number: str, requester_country: str | None, requester_number: str | None) -> dict:
    body: dict[str, str] = {"countryCode": country, "vatNumber": number}
    if requester_country and requester_number:
        body["requesterMemberStateCode"] = requester_country
        body["requesterNumber"] = requester_number
    resp = requests.post(VIES_URL, json=body, timeout=30)
    if resp.status_code >= 500:
        # VIES occasionally routes to unavailable national databases — surface that.
        return {
            "error": "VIES upstream error — some national VAT registries are unavailable at times, retry in a few minutes",
            "status": resp.status_code,
            "body": resp.text[:500],
        }
    if resp.status_code == 400:
        return {"error": "Bad request (usually malformed VAT number format)", "status": 400, "body": resp.json() if resp.content else None}
    resp.raise_for_status()
    data = resp.json()

    # Annotate the response with a plain-language interpretation.
    interpretation = "VALID — this VAT number is registered in VIES; you can issue a 0% VAT (reverse-charge) invoice."
    if not data.get("valid"):
        interpretation = "INVALID — VIES has no record of this VAT number. Do NOT issue a 0% VAT invoice; charge Polish VAT (23%) instead until the counterparty proves valid EU VAT status."

    result: dict[str, Any] = {
        "interpretation": interpretation,
        "vies_response": data,
    }
    if data.get("valid") and (requester_country and requester_number):
        rid = data.get("requestIdentifier", "").strip()
        if rid:
            result["consultation_number"] = rid
            result["consultation_note"] = "Keep this number as legal proof of the VIES check for tax audit purposes."
        else:
            result["consultation_note"] = "No consultation number returned. VIES only issues one when BOTH the checked VAT and the requester VAT are currently valid. Verify your own VAT is active."
    return result


server = Server("vies")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="check_vat",
            description=(
                "Check an EU VAT number against the VIES database (the EU-wide cross-border VAT validator). "
                "Returns valid/invalid + registered name and address if the national database returns them. "
                "Accepts either (country_code, vat_number) separately or a combined `vat` like 'PL5252344078'. "
                "For Polish JDG issuing 0% VAT invoices to EU B2B customers: ALSO pass requester_country + requester_vat "
                "with your own PL VAT — VIES will return a consultation_number that serves as legal proof of the check. "
                "Keep this number for your records. VIES will not issue a consultation number if EITHER VAT is invalid."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "country_code": {"type": "string", "description": "2-letter EU country code (e.g., PL, DE, FR). Greece uses EL, not GR. XI is Northern Ireland."},
                    "vat_number": {"type": "string", "description": "VAT number without country prefix. Dashes/spaces will be stripped."},
                    "vat": {"type": "string", "description": "Alternative: combined form like 'PL5252344078'. If provided, country_code and vat_number are ignored."},
                    "requester_country": {"type": "string", "description": "Optional: your own 2-letter country code (e.g., PL). Required together with requester_vat to obtain a consultation number."},
                    "requester_vat": {"type": "string", "description": "Optional: your own VAT number without country prefix. Combined with requester_country to obtain a consultation number as legal proof of the check."},
                },
            },
        ),
        Tool(
            name="list_supported_countries",
            description="List the country codes supported by VIES (all 27 EU member states, plus XI for Northern Ireland).",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "check_vat":
        combined = arguments.get("vat")
        if combined:
            country, number = _split_combined_vat(combined)
        else:
            country_raw = arguments.get("country_code")
            number_raw = arguments.get("vat_number")
            if not country_raw or not number_raw:
                raise ValueError("Provide either `vat` (e.g., 'PL5252344078') or both `country_code` and `vat_number`.")
            country = country_raw.strip().upper()
            number = _clean_vat_number(number_raw)

        country = _validate_country(country)

        requester_country = arguments.get("requester_country")
        requester_vat = arguments.get("requester_vat")
        if requester_country:
            requester_country = _validate_country(requester_country)
        if requester_vat:
            requester_vat = _clean_vat_number(requester_vat)
        # If only one side of the requester pair is given, ignore both — VIES needs both or neither.
        if bool(requester_country) != bool(requester_vat):
            requester_country = None
            requester_vat = None

        result = _check_vat(country, number, requester_country, requester_vat)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    if name == "list_supported_countries":
        return [TextContent(type="text", text=json.dumps(SUPPORTED_COUNTRIES, ensure_ascii=False, indent=2))]

    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def sync_main():
    """Sync entry point for `honest-vies-mcp` console script."""
    asyncio.run(main())


if __name__ == "__main__":
    sync_main()
