# Mech Royale Survivor

A survival-first bot for the official mechfight/1 protocol. It uses Python's standard library and the unchanged official Python wrapper. It aims to improve placement by avoiding crowded fights, escaping danger and moving into the next safe zone early.

## Map and movement

The bot loads the complete mounted map from hello.map.dir (normally /arena):

- All 774,680 signed terrain samples, with bilinear height sampling.
- All 259 solid prisms: 223 buildings, 27 stadium sections and 9 bridges.
- Building holes/courtyards, roofs, bridge decks and underpasses.
- All 1,560 trees for sight estimates. Trees block neither movement nor shots.
- Map bounds and every other world.json section. Cars, water, parking and barriers stay available as scenery; official rules say they do not block movement.

Routes use several waypoints and continue searching across observations, with a small work budget per decision. The route grid covers the map rather than only one blocking building. Route segments and tactical dodges/strafe moves check cylinder clearance, live mech size, slopes, steps and guarded roof drops. Movement caches are reset when the mech's size or walking limits change.

Air movement uses a short prediction with momentum, air acceleration, gravity, rise limits, jet fuel and landing checks. A blocked route can attempt an energy-limited jet escape after checking the overhead and lateral path.

These are bounded planning checks, not a copy of the server's full physics engine. The 6 m route grid can miss narrow passages, long searches can run out of their node budget, and large drops are deliberately avoided. The bot cannot assume every rooftop is reachable with its remaining energy.

## Strategy

Enemy memory belongs only to observed mech IDs. Predictions fade, uncertainty grows, and predicted motion stops at map obstacles. Sound creates a broad risk area, not an invented enemy location. Damage updates aggression only when the event identifies an attacker.

Observed NPC drones have their own bounded memory. Their proximity and recent attacks affect route danger using the official aggro/chase ranges. Their hidden spawn/home positions are never guessed, and the bot does not farm drones.

Survival and zone movement override loot and firing. Target and destination choices have short holding periods to reduce switching. Visible cubes, weapons and uncontested landed drops can be gathered when the route is safe.

Gun aim uses one intercept calculation. Mortars use gravity and a checked arc; lasers charge and release correctly. Shots must agree with actual torso aim and pass 3D obstruction checks. Inferred tracks are not fired upon.

## Run the checks

Python 3.9+ is needed for development. No third-party runtime packages are required. From this project root, first download the official kit if work/official-kit is absent:

~~~sh
python3 tools/fetch_official_kit.py
python3 -m unittest discover -s tests -v
python3 tests/strictness_runner.py --all --seed 17 --seed 29
python3 tools/check_official.py --sample
python3 tools/check_official.py
~~~

On Windows, use python instead of python3. The kit fetcher refuses to overwrite an existing kit. The downloaded kit was compared with a fresh official download on 2026-11-22; its SHA-256 is recorded in reports/map_coverage.json.

There are exactly five synthetic test levels. Fixtures are checked against the official schema. Level 5 also runs all 300 recorded observations, full-map loading, airborne states and larger threat inputs. Latency is measured without allocation tracing; a separate pass measures allocations. Timing and behavior failures are separate release gates.

The official checker tests protocol and response times. Its recorded world does not react to our actions. Neither it nor the synthetic suite proves a match result or placement score.

## Docker and VM checks

The Dockerfile follows the official Python Dockerfile, pins the base image by digest, and copies only the five runtime modules. It does not bundle the map. On Linux with Docker:

~~~sh
sudo docker build --platform linux/amd64 -t mech-agent:map-aware .
python3 tools/check_official.py --image mech-agent:map-aware
python3 tools/measure_sandbox.py --image mech-agent:map-aware
~~~

The checker helper invokes the unchanged official checker with no network, 1 CPU, 512 MB memory, read-only root, user 65534, writable /tmp of 64 MB, and the official arena mounted read-only at /arena. The measurement helper separately records in-container peak RSS.

The existing Google Cloud VM is Debian 12 on ARM64, not Ubuntu/AMD64. Its separate bot project is /home/ayode/mech-royale. Docker and AMD64 emulation were installed there. Native ARM timing and emulated AMD64 sandbox timing are reported separately; emulation is not a prediction of competition-host speed.

Reports:
- reports/test_matrix.md: workstation five-level results on seeds 17 and 29.
- reports/official-native.json: workstation official checker output and exact command.
- reports/map_coverage.json: loaded map coverage and source hashes.
- reports/vm/: final VM unit tests, five-level runs, official native/Docker checks, image details and sandbox memory.

The latest measured results are summarized in reports/validation_summary.json. All timings are measurements on the named host, not match scores.

## Public repository and next step

The runtime entrypoint and Dockerfile are at the repository root. work/, outputs/ and bytecode caches are excluded from Git. The map and downloaded kit are development inputs; the runtime uses the read-only mounted map.

No repository has been published and no tournament submission has been made. The next useful strategy test is a real practice match: record placement, zone deaths, stuck time and encounter outcomes, then tune from those results. The kit has no reactive local match simulator.

Official sources: [challenge](https://www.joinbuilders.org/buildathon/tracks/builders), [protocol](https://www.joinbuilders.org/buildathon/tracks/builders/files/protocol.md?inline=1), [kit](https://www.joinbuilders.org/buildathon/tracks/builders/files/mechfight-kit.tar.gz).
