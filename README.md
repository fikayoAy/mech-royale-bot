# Mech Royale Survivor

A survival-first mechfight/1 bot. The active working copy is `C:/Users/ayode/machina/mech-royale-merge`. The older IDE folder is not the release copy.

## What the bot does

- Loads the full public terrain, buildings, stadium, bridges, courtyards, roofs, trees and bounds. Other map sections remain available as scenery.
- Tracks only known opponents and observed NPCs. Lost tracks fade and gain uncertainty; sounds add broad activity areas without creating enemy identities.
- Keeps observed aggression, chase, retreat, stationary-attack and isolation evidence. Unknown values stay unknown. These are tendencies, not claims about hidden intent.
- Records contact, damage, confirmed kills, lost contact and defeat after contact. Defeat does not identify a killer. Encounter damage trades feed bounded threat estimates.
- Compares estimated fight duration, health, weapons, energy and nearby support. It favors escape from crowded or poor fights and uses short holds to limit target and mode changes.
- Uses observe, gather, reposition, engage, disengage, recover, evade and zone-move modes, with guarded jet escape when blocked. Pursuit escape uses boost with a fuel reserve and separate start/stop thresholds.
- Checks routes and local steering against terrain, solids, live mech size, steps and slopes. It retries a finer grid, replans dangerous routes and changes checked headings when stuck.
- Aims using observed velocity and weapon mechanics from `hello.config`. Clear gun shots can continue during escape. New laser charges and mortar shots stay blocked under pressure. Quiet low magazines reload early; safe pickups can replace a weaker secondary weapon.
- Records decision time, prediction error, stuck time, zone damage, ammunition, modes, encounters and the supplied end result. Stdout contains protocol messages only.

`virtual_map.py` combines the world model, enemy tracker and heatmap to avoid copying state between modules. Other policy parts live in `config.py`, `behavior_profiler.py`, `encounters.py`, `target_selector.py`, `survival.py`, `decision_engine.py`, `combat.py` and `navigation.py`.

The wrapper retains the official latest-observation handling. Small additions call our fallback after an error and export the end summary. The official checker itself is unchanged.

## Run locally

Python 3.9+; runtime uses the standard library only. From the repository root:

```sh
python3 tools/fetch_official_kit.py
python3 -m unittest discover -s tests -v
python3 tests/strictness_runner.py --all --seed 17 --seed 29
python3 tools/check_official.py --sample
python3 tools/check_official.py
```

If the kit is already elsewhere, skip the download and set `MECHFIGHT_KIT` to its root, which contains `protocol.md`, `check/` and `arena/`. On Windows use `python`, and for example:

```powershell
$env:MECHFIGHT_KIT='C:\Users\ayode\machina\mech-royale-upload-backup-20261122-030550\work\official-kit\mechfight-kit'
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -m unittest discover -s tests -v
```

There are exactly five levels. Select one with `--level 1` through `--level 5`; `--all` runs all five. Levels change test inputs, never live policy or safety rules. Level 5 includes 4,801 synthetic decisions over 480 seconds plus all 300 official recorded observations, with different legal initial ground positions for each seed. Synthetic sequences are scripted inputs, not a physics simulator.

Tests validate observations and actions against the official schema and check uncertainty, pursuit, energy reserve, recovery, zone priority, reload, crowds, stationary attacks, misleading history, encounter outcomes, stuck recovery, mode switching and bounded history. Timing excludes allocation tracing; allocation checks run separately.

## Build and test on Linux AMD64

Docker setup tested on the separate Ubuntu 24.04 AMD64 validation VM:

```sh
sudo apt-get update
sudo apt-get -o DPkg::Lock::Timeout=180 install -y docker.io
sudo systemctl start docker
export PYTHONDONTWRITEBYTECODE=1
export MECHFIGHT_KIT="$PWD/kit/mechfight-kit"
sudo docker build --platform linux/amd64 --no-cache -t mech-agent:roadmap .
python3 tools/validate_sandbox.py --image mech-agent:roadmap --reports-dir reports/roadmap-amd64
python3 tools/check_official.py --image mech-agent:roadmap --reports-dir reports/roadmap-amd64
python3 tools/measure_sandbox.py --image mech-agent:roadmap --reports-dir reports/roadmap-amd64
```

For a fresh checkout the fetcher instead places the kit in `work/official-kit/mechfight-kit`; use that path for `MECHFIGHT_KIT`.

The pinned Python image copies only runtime files. The map is mounted separately. The sandbox harness imports runtime code from the built image at `/bot` and mounts its test harness and kit read-only. It uses exactly 1 CPU, 512 MB, no network, read-only root, uid 65534 and a 64 MB `/tmp`. No writable source mount is used. All five levels, two seeds and unit tests run inside those limits. The unchanged official checker is a separate release gate and is repeated three times on the final image.

The original ARM64 dataset VM is separate. Native AMD64 measurements are saved under `reports/roadmap-amd64/`; earlier ARM and emulation reports describe older versions. The Machina dataset jobs remain stopped.

## Evidence and limits

Current release evidence is summarized in `reports/validation_summary.json`, `reports/roadmap_completion.json` and `reports/test_matrix.md`. Raw reports include source hashes, exact commands, build duration, process memory, behavior assertions and checker output. All five levels and the unchanged official checker must pass before release.

Tests cannot predict placement. The kit's recorded observations do not react to our actions. Even an end message in that recording is fixture data, not our match result. The user reported practice scores of 0.25 and 0.96; the 0.96 receipt and commit are unknown. This roadmap version needs its own real scored run.

Routes, cover rays, weapon estimates, behavior tendencies and air movement are bounded planning approximations. Narrow passages and long searches may be missed. Unknown enemy equipment/health uses cautious defaults. Branch weights and fight estimates are not measured probabilities. The server controls the actual physics and outcome.

## Policy and diagnostics

`MECH_POLICY=survival` is the default; `balanced` and `cautious` are separate tuning presets. `MECH_POLICY_FILE` can point to a readable JSON file with named `Policy` fields. Values are checked at startup. These settings are independent of the five test levels.

`MECH_DEBUG_MAP=1` adds capped drawings. `MECH_TELEMETRY_STDERR=0` disables the compact end summary. Optional `MECH_TELEMETRY_FILE=/tmp/match.json` saves a fuller bounded summary; other output paths are rejected. No runtime network or default file writes are used.

The offline viewer is `reports/virtual_map.html`. Rebuild with `python3 tools/export_map_viewer.py`. It shows recorded observations and estimates, with timeline, camera and layer controls.

## Practice and release

Repository: https://github.com/fikayoAy/mech-royale-bot . Keep `Dockerfile` at the root. Development downloads, outputs and bytecode caches are excluded. Release tooling checks the 20 MB tracked-file limit; the runtime does not bundle the public map.

Submit the repository URL on the official challenge page after approval. The roadmap explicitly says not to automate tournament submissions without approval. No submission is triggered by any script here. After a real score arrives, record its exact commit and receipt:

```sh
python3 tools/record_practice.py --score 0.96 --commit ACTUAL_COMMIT --receipt ACTUAL_RECEIPT --notes "real result"
```

Those arguments are an example, not a recorded score for this version. Keep the best known scored commit. Use actual stuck/zone/encounter traces to choose the next change; a lower score alone does not identify a cause.

Official sources: [challenge](https://www.joinbuilders.org/buildathon/tracks/builders), [protocol](https://www.joinbuilders.org/buildathon/tracks/builders/files/protocol.md?inline=1), [kit](https://www.joinbuilders.org/buildathon/tracks/builders/files/mechfight-kit.tar.gz). Rules were checked on 2026-11-22.
