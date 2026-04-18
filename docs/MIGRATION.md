# Migration Guide

This guide covers upgrading between major versions of Asterisk AI Voice Agent.

## v6.3.2 to v6.4.0

**No breaking changes.** All new features are additive or opt-in.

```bash
# Standard upgrade
git pull
docker compose -p asterisk-ai-voice-agent up -d --build --force-recreate
```

New in v6.4.0:
- Attended transfer streaming & screening modes (`basic_tts`, `ai_briefing`, `caller_recording`)
- Sherpa offline STT with VAD-gated transducer mode (`SHERPA_MODEL_TYPE=offline`)
- T-one STT backend for Russian telephony ASR (`LOCAL_STT_BACKEND=tone`)
- Silero TTS backend with multi-language support (`LOCAL_TTS_BACKEND=silero`)
- HTTP tool JSONPath `[*]` wildcard array extraction
- Per-message conversation timestamps in Call Log UI
- Fullscreen toggle for dashboard panels
- Provider-agnostic runtime tool guidance for transfer targets
- Live Agents UI redesign with auto-polling

If you want the new Russian speech backends, rebuild with build args:
```bash
# T-one STT (Russian)
docker compose build --build-arg INCLUDE_TONE=true local_ai_server

# Silero TTS (Russian + multi-language)
docker compose build --build-arg INCLUDE_SILERO=true local_ai_server

# Both
docker compose build --build-arg INCLUDE_TONE=true --build-arg INCLUDE_SILERO=true local_ai_server
```

Deprecated configs (still functional, will be removed in a future release):
- `tools.attended_transfer.ai_summary` → use `screening_mode: ai_briefing`
- `tools.attended_transfer.pass_caller_info_to_context` → use `screening_mode: basic_tts`
- `transfer_call` / `transfer_to_queue` legacy tools → use unified `blind_transfer`

## v6.3.1 to v6.3.2

**No breaking changes.** All new features are additive or opt-in.

```bash
# Standard upgrade
git pull
docker compose -p asterisk-ai-voice-agent up -d --build --force-recreate
```

New in v6.3.2:
- Microsoft Azure Speech Service STT & TTS pipeline adapters (REST batch, WebSocket streaming, SSML synthesis)
- MiniMax LLM M2.7 pipeline adapter via OpenAI-compatible API
- Call Recording Playback in Admin UI Call Details modal
- Google Calendar delete() with timezone fixes
- Azure SSRF prevention, PII logging discipline, input validation hardening

## v6.2.x to v6.3.1

**No breaking changes.** All new features are additive or opt-in.

```bash
# Standard upgrade
git pull
docker compose -p asterisk-ai-voice-agent up -d --build --force-recreate
```

New in v6.3.1:
- Local AI Server: backend enable/rebuild flow, expanded model catalog, GGUF validation, checksum sidecars
- GPU ergonomics: `LOCAL_LLM_GPU_LAYERS=-1` auto-detection, GPU compose overlay improvements
- CPU-first onboarding: defaults to `runtime_mode=minimal` on CPU-only hosts
- Security hardening: path traversal protection, concurrent rebuild race fix, active-call guard on model switch
- Structured local tool gateway with hangup guardrails
- CLI `agent check --local` / `--remote` for Local AI Server validation
- New STT backends: Whisper.cpp (`LOCAL_STT_BACKEND=whisper_cpp`)
- New TTS backend: MeloTTS (`LOCAL_TTS_BACKEND=melotts`)

If you use `local_ai_server` with optional backends, rebuild to pick up new capabilities:
```bash
docker compose build --build-arg INCLUDE_FASTER_WHISPER=true --build-arg INCLUDE_WHISPER_CPP=true local_ai_server
```

## v6.1.1 to v6.2.0

**No breaking changes.** All new features are additive or opt-in.

```bash
# Standard upgrade
git pull
docker compose -p asterisk-ai-voice-agent up -d --build --force-recreate
```

New in v6.2.0:
- NumPy audio resampler replaces legacy `audioop.ratecv` (fixes crackling)
- Google Live native audio latest model support (`gemini-2.5-flash-native-audio-latest`)
- Google Live VAD tuning, TTS gating, farewell/hangup hardening
- Telnyx AI Inference LLM pipeline provider (`telnyx_llm`)
- Agent CLI `check --fix` auto-repair
- Admin UI tool catalog and Google Live settings
- 13 call termination fixes across all providers

## v6.0.0 to v6.1.1

**No breaking changes.** All new features are additive or opt-in.

```bash
# Standard upgrade
git pull
docker compose -p asterisk-ai-voice-agent up -d --build --force-recreate
```

New in v6.1.1:
- Operator config overrides via `config/ai-agent.local.yaml` (optional, git-ignored)
- Live agent transfer tool (opt-in via tool allowlist)
- ViciDial outbound dialer compatibility (opt-in via `.env`)

## v5.x to v6.0.0

### Breaking Changes

1. **OpenAI Realtime API version default changed to GA**
   - The default `api_version` is now `ga` (was `beta`)
   - GA uses nested audio schema (`audio.input.format` / `audio.output.format` with MIME types)
   - **To keep old behavior**: Set `api_version: beta` explicitly in your provider config

2. **Email template autoescaping enabled**
   - `template_renderer.py` now uses `autoescape=True` by default
   - Custom HTML templates that use raw HTML variables need Jinja2's `| safe` filter

### Upgrade Steps

```bash
# 1. Backup your configuration
cp .env .env.backup
cp config/ai-agent.yaml config/ai-agent.yaml.backup

# 2. Pull the latest code
git pull

# 3. Run preflight to update environment
sudo ./preflight.sh --apply-fixes

# 4. Rebuild and restart all containers
docker compose -p asterisk-ai-voice-agent up -d --build --force-recreate

# 5. Verify health
curl http://localhost:15000/health
agent check
```

If you were using `api_version: beta` explicitly, no OpenAI changes are needed. If you relied on the default, review your OpenAI provider config.

## v4.x to v6.0.0

### Major Changes

- **Config schema v4**: Milestone 13 migrated configuration format. Run `scripts/migrate_config_v4.py --dry-run` to preview changes, then `--apply` to migrate.
- **Diagnostic settings moved to `.env`**: Settings like `DIAG_EGRESS_SWAP_MODE`, `DIAG_ENABLE_TAPS`, and `STREAMING_LOG_LEVEL` are now environment variables, not YAML keys.
- **Prometheus/Grafana removed**: The monitoring stack is no longer shipped. Use Admin UI Call History for per-call debugging and bring your own Prometheus if needed.
- **Admin UI added**: Web interface on port 3003 for configuration and monitoring.
- **Multiple new providers**: Google Live, ElevenLabs Agent added since v4.x.
- **Tool calling system**: Unified tool framework with telephony and business tools.

### Upgrade Steps

```bash
# 1. Backup everything
cp -r config/ config.backup/
cp .env .env.backup

# 2. Pull the latest code
git pull

# 3. Run config migration (preview first)
python scripts/migrate_config_v4.py --dry-run
python scripts/migrate_config_v4.py --apply

# 4. Run preflight
sudo ./preflight.sh --apply-fixes

# 5. Rebuild containers
docker compose -p asterisk-ai-voice-agent up -d --build --force-recreate

# 6. Verify
agent check
curl http://localhost:15000/health
```

### Post-Migration

- Access Admin UI at `http://localhost:3003` (login: admin/admin, change immediately)
- Review your provider configuration in the Admin UI Setup Wizard
- Check Call History for your first test call to verify everything works

## General Upgrade Procedure

For any version upgrade:

1. **Backup** your `.env`, `config/ai-agent.yaml`, and `config/ai-agent.local.yaml`
2. **Pull** the latest code: `git pull` (or use `agent update` which handles backup/restore automatically)
3. **Run preflight**: `sudo ./preflight.sh --apply-fixes`
4. **Rebuild**: `docker compose -p asterisk-ai-voice-agent up -d --build --force-recreate`
5. **Verify**: `agent check` and make a test call

For detailed release notes, see [CHANGELOG.md](../CHANGELOG.md).
