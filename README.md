# honest-vies-mcp

Local MCP server for the **EU VIES VAT number validator** (the authoritative EU-wide check used before issuing 0% VAT cross-border invoices) — no authentication, no rate limit, no cloud middle.

Part of the [honest-mcp family](https://github.com/bartosz-kuc?tab=repositories) of small, auditable, local-first MCP servers.

## Why

A Polish JDG (or any EU business) issuing a **0% VAT reverse-charge invoice** to an EU B2B customer must first verify that customer's VAT number is registered in VIES — and keep evidence of the check. Skipping this and it turns out the customer's VAT is invalid, the Polish tax office will demand 23% VAT from **you**, retroactively, plus interest.

This server puts VIES a single tool call away. Ask your AI "verify DE143454214 before I issue this invoice" and you get: valid/invalid, registered name and address, and a consultation number for your records if you provided your own VAT.

Same trust model as the rest of the family: data flows only between your machine and the European Commission.

## Features

Two tools:

- `check_vat` — validate a single EU VAT number. Optionally pass your own VAT (`requester_country` + `requester_vat`) to receive a consultation number as legal proof of the check.
- `list_supported_countries` — the 27 EU country codes + `XI` for Northern Ireland.

## Data source

- Endpoint: [ec.europa.eu/taxation_customs/vies/](https://ec.europa.eu/taxation_customs/vies/) REST API
- No API key, no registration
- Coverage: 27 EU member states + Northern Ireland (`XI`)
- Note: Greece uses country code `EL`, not `GR`

## Requirements

- Python 3.10+

## Setup

```bash
git clone https://github.com/bartosz-kuc/honest-vies-mcp.git
cd honest-vies-mcp
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

Register with Claude Code:

```bash
claude mcp add vies /absolute/path/to/venv/bin/python /absolute/path/to/server.py
```

Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "vies": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["/absolute/path/to/server.py"]
    }
  }
}
```

## Example usage

> "Verify German VAT DE143454214 before I invoice them."

`check_vat(country_code="DE", vat_number="143454214")` → valid/invalid + name/address.

> "Verify the same, but also get a consultation number — my VAT is PL7393933151."

`check_vat(vat="DE143454214", requester_country="PL", requester_vat="7393933151")` → response includes a `consultation_number` field. Save that number with the invoice.

> "What's the EU VAT country code for Greece again?"

`list_supported_countries()` → confirms Greece is `EL`, not `GR`.

## Data flow

```
Your AI client
     ↕  MCP stdio
This server (Python, on your machine)
     ↕  HTTPS
ec.europa.eu (VIES)
```

No cloud middle. Nothing to log in to. No telemetry.

## For Polish JDG owners

The tax law bit: **art. 42 ust. 1 pkt 1 ustawy o VAT** — before applying the 0% rate on an intra-community supply (WDT), the seller must have a valid VAT-UE number of the buyer. **Art. 100 ust. 8 pkt 1** — proof of the check is expected on audit. The `consultation_number` (VIES's `requestIdentifier`) is the standard evidence: it's a unique code tying your check to a specific date and pair of VAT numbers. Store it with the invoice.

Non-obvious bits VIES will bite you with:
- If your OWN VAT (the requester) is not currently active in VIES, no consultation number is returned even when the checked VAT is valid.
- VIES is an EU-wide switch — validation happens against the national database of the country in the VAT prefix. Occasionally a national database is offline; the server surfaces that clearly instead of pretending it's a valid/invalid result.

## Author

**Bartosz Kuć** — Warsaw-based developer, JDG owner running [skanfirmy.pl](https://skanfirmy.pl).

- GitHub: https://github.com/bartosz-kuc

## License

MIT — see [LICENSE](LICENSE).

## Related

- [honest-gmail-mcp](https://github.com/bartosz-kuc/honest-gmail-mcp) — local Gmail MCP
- [honest-calendar-mcp](https://github.com/bartosz-kuc/honest-calendar-mcp) — local Google Calendar MCP
- [honest-drive-mcp](https://github.com/bartosz-kuc/honest-drive-mcp) — local Google Drive MCP with permission management
- [ksef-mcp](https://github.com/bartosz-kuc/ksef-mcp) — Polish KSeF (e-invoicing) MCP
- [nip-krs-mcp](https://github.com/bartosz-kuc/nip-krs-mcp) — Polish company registry MCP (biała lista + KRS)
- [nbp-mcp](https://github.com/bartosz-kuc/nbp-mcp) — NBP MCP: exchange rates + gold fixing for Polish accounting
