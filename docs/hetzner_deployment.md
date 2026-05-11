# Atlas Hetzner Deployment

Hetzner is now the primary production target for Atlas Capture.

## Target
- Host: `167.235.253.229`
- Recommended app user: `atlas`
- Recommended app path: `/srv/atlas/OCR_annotation_Atlas`
- OS target: Ubuntu

## Runtime Model
- Native Ubuntu deployment
- Python virtual environment in `.venv`
- Playwright + headless Chromium
- `systemd` services
- Sequential multi-account execution
- Gemini API rotation with `round_robin`

## Required Runtime Files
- `configs/production_hetzner.yaml`
- `configs/accounts/index.yaml`
- `configs/accounts/danatimer.yaml`
- `configs/accounts/wafaabayoumi.yaml`
- `configs/accounts/amirakamelkorany.yaml`
- `configs/accounts/badrbayoumi865.yaml`
- `.env`
- `.state/accounts/<account>/atlas_auth.json`

## Bootstrap
Run on the server as root:

```bash
git clone https://github.com/aymank2020/OCR_Annotation_Atlas.git /srv/atlas/OCR_annotation_Atlas
cd /srv/atlas/OCR_annotation_Atlas
bash setup_hetzner_atlas.sh
```

The bootstrap script:
- creates the `atlas` user if missing
- configures swap
- installs Python, ffmpeg, and Playwright dependencies
- creates `.venv`
- installs Python requirements
- installs `atlas-solver.service`
- installs `atlas-discord-bot.service`
- installs the solver health timer

## Environment Variables
Recommended numbered per-account keys:
- `ATLAS_LOGIN_EMAIL1` / `ATLAS_EMAIL1` / `GMAIL_USER1` / `GMAIL_EMAIL1` / `GMAIL_APP_PASSWORD1`
- `ATLAS_LOGIN_EMAIL2` / `ATLAS_EMAIL2` / `GMAIL_USER2` / `GMAIL_EMAIL2` / `GMAIL_APP_PASSWORD2`
- `ATLAS_LOGIN_EMAIL3` / `ATLAS_EMAIL3` / `GMAIL_USER3` / `GMAIL_EMAIL3` / `GMAIL_APP_PASSWORD3`
- `ATLAS_LOGIN_EMAIL4` / `ATLAS_EMAIL4` / `GMAIL_USER4` / `GMAIL_EMAIL4` / `GMAIL_APP_PASSWORD4`

Runtime behavior:
- `configs/accounts/index.yaml` rotates accounts sequentially
- each account gets `5` tasks per turn
- the runner rests `45s` before handing off to the next account
- accounts without both readiness signals (`storage_state` or Gmail OTP credentials) are skipped safely

Shared service keys:
- `DISCORD_BOT_TOKEN`
- `DISCORD_GUILD_ID`
- `COMMAND_CHANNEL_ID`

## Services
Start the main services:

```bash
sudo systemctl start atlas-solver.service
sudo systemctl start atlas-discord-bot.service
```

Enable on boot:

```bash
sudo systemctl enable atlas-solver.service
sudo systemctl enable atlas-discord-bot.service
```

The command hub is intentionally local-only. Start it only when needed:

```bash
sudo systemctl start atlas-command-hub.service
```

SSH tunnel example:

```bash
ssh -L 8500:127.0.0.1:8500 atlas@167.235.253.229
```

## Health Checks
```bash
systemctl status atlas-solver.service
systemctl status atlas-solver-health.timer
journalctl -u atlas-solver.service -n 100 --no-pager
tail -n 100 /srv/atlas/OCR_annotation_Atlas/outputs/solver_service.log
```

## Safe Updates
```bash
cd /srv/atlas/OCR_annotation_Atlas
bash safe_update_preserve_local.sh main /srv/atlas/OCR_annotation_Atlas
systemctl restart atlas-solver.service
systemctl restart atlas-discord-bot.service
```

## Migration From Windows
Run from the workstation:

```powershell
.\migrate_to_vps.ps1 -VpsHost 167.235.253.229 -User atlas -IncludeState
```

The migration now includes:
- code
- `.env`
- account configs
- saved Atlas storage state JSON files

It excludes:
- Windows Chrome profiles
- `.venv`
- outputs
- heavy archives and caches

## Account Scheduler Rules
- `scheduler.mode` is `sequential`
- `max_parallel_accounts` remains `1`
- each account gets its own generated config
- each account gets its own `storage_state_path`
- each account gets its own `output_dir`

## Gemini Rotation Rules
- priority: `gemini.api_keys` -> `GEMINI_API_KEYS_POOL` -> legacy single-key env vars
- duplicate keys are removed while preserving first-seen order
- `round_robin` advances on each new request
- retriable failures can switch to the next key in the same request
