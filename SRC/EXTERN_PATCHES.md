# External patches

This project carries patches against two upstream source trees,
[RPCS3](https://github.com/RPCS3/rpcs3) and [rpcn](https://github.com/RipleyTom/rpcn).
They are applied to the cloned trees by `SRC\apply-patches.bat` (Windows) or
`SRC\apply-patches.sh` (Linux). Which patches apply, and in what order, is defined
by one file: `SRC\PATCH\series`, the single source of truth every applier reads.
The per-patch rationale follows below, keyed by filename.

The kit modifies upstream because the game depends on
two PSN features that aren't otherwise available in an offline or community-RPCN
setup, and to work around lobby-wide freezes we observed in RPCS3's P2P
TCP-over-UDP stack whenever any player disconnected:

- **Title Small Storage (TSS).** The game is online-only and pulls server-side
  TSS blobs to complete its login phase. Without them, login fails with
  "Failed to connect to Playstation Network".
- **Title User Storage (TUS).** Saves live exclusively in the cloud. The game's
  save format is fragile, and the game has its own server-side recovery
  routines whose protocol we haven't reverse-engineered. A corrupted cloud save
  leaves the player stuck with no way to fix it. We work around that by
  mirroring every cloud-save write to local disk so the launcher can put a
  known-good copy back.
- **P2PS disconnect handling.** When any player in a lobby dropped or timed
  out, every remaining player froze. The patch changes several behaviours
  in `lv2_socket_p2ps`, `tcp_timeout_monitor`, and the signaling handler;
  with it applied, lobbies recover from disconnects.

All patches were developed against the game object of this repository. They
are not claimed to be the correct fix for every RPCS3 game, but may be
useful as a reference point.

## RPCS3: `tss-support.patch`

Modifies `rpcs3/Emu/Cell/Modules/sceNpTus.cpp` and `rpcs3/Emu/NP/np_requests.cpp`.

### TSS file serving

`sceNpTssGetData` and `sceNpTssGetDataAsync` previously returned the stub
"no file" response. The game treats this as a fatal error and login fails with
"Failed to connect to Playstation Network". The patch replaces the stubs with a
real implementation (`scenp_tss_serve_file`):

1. Read from `<config_dir>/tss/<titleId>-<slot>.tss` if present.
2. Otherwise fetch over HTTP from
   `http://<rpcn_host>:<rpcn_port + 2>/tss/<titleId>/<titleId>-<slot>.tss`
   via libcurl (`scenp_tss_fetch_from_rpcn`).
3. If neither yields a file, fall through to the original stub.

The two-source design is for decentralization. TSS files can be distributed
locally with each install, or hosted once on the community RPCN server and
fetched on demand. Neither path is privileged. Range parameters (`offset`,
`lastByte`) are honoured; `ifParam` is logged but ignored.

The PSN online check at the top of both functions was removed. TSS data here
comes from the local filesystem or RPCN, never the real PSN, so the check would
only prevent legitimate offline use.

### World list allocation fix and padding

In `np::reply_get_world_list` (`np_requests.cpp`), two changes:

- The `SceNpMatching2World` array allocation was inside an
  `if (!world_list.empty())` branch, leaving `world_info->world` as a null
  pointer when RPCN returned no worlds. The allocation is now unconditional.
- The world list is padded with `worldId = 65537` until its length is at least
  10.

The padding works around a game-side assumption: the game reads
past the end of the returned list and crashes when the list is too short. The
proper fix would be on the game side, which we can't touch. The actual
workaround lives in our fork of RPCN: `servers.cfg` registers 5 worlds for
the game's community ID (see below), which is enough to avoid the crash. The client-side
padding to 10 entries here is an additional safety net.

### TUS restore via one-shot local files

`scenp_tus_serve_restore` (called from `scenp_tus_get_data` before the normal
RPCN path) checks for a file at
`<config_dir>/tus/<commId>/<npId>/<slot20d>.tdt.restore`:

- Empty file: report `SCE_NP_COMMUNITY_SERVER_ERROR_USER_STORAGE_DATA_NOT_FOUND`,
  matching RPCN's own "no data" response. The game treats this as a fresh
  account.
- Non-empty file: serve its contents as the TUS payload.

The file is deleted after the read regardless, so the next `GetData` falls
through to RPCN normally. This is the hook the launcher's "Backup / Restore"
and "New Game" features use to take effect on the next game boot.

### Automatic TUS backup on SetData

In `np::reply_tus_set_data` (`np_requests.cpp`), the patch writes a timestamped
local copy of the outgoing TUS payload before forwarding it to RPCN:

```
<config_dir>/tus/<commId>/<npId>/backups/YYYY-MM-DD_HHMMSS_<commId>_<slot20d>.tdt
```

The game's save format is fragile and the game's own server-side recovery
routines use a protocol we haven't reverse-engineered, so a corrupted cloud
save can't be fixed through normal game flow. The local mirror is a workaround:
every cloud-save write is dumped to disk, and the launcher's restore flow
hands a known-good copy back through the one-shot file path above.

## RPCS3: `invite-attachment-fix.patch`

Modifies `rpcs3/Emu/Cell/Modules/sceNp.cpp`, `rpcs3/Emu/NP/np_handler.cpp`,
`rpcs3/Emu/NP/np_handler.h`, `rpcs3/Emu/NP/np_cache.cpp`, `rpcs3/Emu/NP/np_cache.h`,
`rpcs3/Emu/NP/np_helpers.h` and `rpcs3/Emu/NP/rpcn_client.cpp`.

Accepting an invite failed with "Failed to join room". The game takes the matching2
server it should join from the top 16 bits of the room id carried inside the
invitation, and it has no other source for it. RPCN allocates bare room ids, so that
field arrived as zero, matched none of the servers the game had just validated, and the
accept stopped before it ever looked up a world.

The patch fills that field in on one value only: the room id inside an outgoing
invitation, rewritten as the message is sent, using the server id of the room the
sender is in. Room ids travelling to RPCN have it masked back off, so the server sees
bare ids exactly as before and needs no change.

Every other room id is left alone. That is deliberate rather than incidental: the game
also puts room ids in its own peer-to-peer lobby traffic and compares them for exact
equality, so a client that rewrote the ids it holds would stop being able to see
players running an unpatched build. Leaving them bare keeps every id this client sends
identical to an unmodified RPCS3's, which is what allows patched and unpatched players
to share a lobby.

**Both players need this build.** An invitation sent by an unpatched build carries no
server id, and nothing on the receiving side can supply one for a room it has not
joined. Accepting an invite on an unpatched build crashes the game and RPCS3.

## RPCS3: `np-localnetinfo-byteorder-fix.patch`

Modifies `rpcs3/Emu/Cell/Modules/sceNp.cpp` (`sceNpSignalingGetLocalNetInfo`)
and `rpcs3/Emu/Cell/Modules/sceNp2.cpp`
(`sceNpMatching2SignalingGetLocalNetInfo`).

Both functions wrote the local and mapped IP addresses into PS3 emulated memory
byte-swapped, so any title that reads its own LAN/WAN address from these APIs to
advertise itself in a room attribute handed peers a corrupted address.

### The bug

`get_local_ip_addr()` / `get_public_ip_addr()` return a `u32` already in network
byte order (the raw `sin_addr.s_addr`, whose in-memory bytes are the IP octets in
order). The destination fields are `be_t<u32>`. A plain assignment to a `be_t`
runs through `to_data()`, which byteswaps on a little-endian host; feeding an
already-network-order value through that swap reverses the octets in emulated
memory. The PS3 Cell CPU is big-endian (host order == network order), so on real
hardware the field simply holds the network-order `s_addr`; only on RPCS3's LE
host does the extra swap corrupt it. For 192.168.1.11 (`C0 A8 01 0B`) the buggy
store produced `0B 01 A8 C0`.

The fix replaces the assignment with
`std::bit_cast<be_t<u32>, u32>(...)`, which reinterprets the network-order bytes
as a `be_t` without re-swapping. This is the same idiom the working sys_net path
already uses (`sys_net_helpers.cpp`, `native_addr_to_sys_net_addr`) to place a
network-order address into a PS3 `be_t<u32>`.

```cpp
info->local_addr  = std::bit_cast<be_t<u32>, u32>(nph.get_local_ip_addr());
info->mapped_addr = std::bit_cast<be_t<u32>, u32>(nph.get_public_ip_addr());
```

The neighbouring `nat_status` / `npport` / `natStatus` fields are left untouched:
those take logical integer constants, for which plain `be_t` assignment is
already correct. This is why, in a captured affected `roomBinAttrExternal` blob,
the port (`SCE_NP_PORT`) survived while the two IPs came through reversed.

### Scope

The corruption is game-visible only and lives on the advertising side: a host
writing its own room blob. RPCN stores `roomBinAttrExternal` as an opaque byte
array and echoes it back verbatim, never parsing it as an IP, so no server change
is needed and the fix works against the existing public RPCN. A searcher reads
the raw blob bytes regardless of its own build, so there is no double-swap risk;
an unpatched host produces the same swapped blob as before, with no regression.
The one mixed-fleet wrinkle is titles that compare their own `GetLocalNetInfo`
WAN against a peer's blob WAN to detect "same public IP, use LAN address": a
patched node's correct WAN will not match an unpatched peer's swapped WAN, which
can defeat that shortcut for two players behind the same router. All-patched and
all-unpatched fleets are each internally consistent, so the patch is best rolled
out to everyone at once.

This is not a standalone fix for "players behind CG-NAT can't see each other's
rooms", which is a P2P reachability failure (symmetric NAT can't complete the UDP
hole punch) that a flat overlay network addresses. It is complementary: it stops
the title's first probe from being aimed at a byte-swapped address that on
symmetric NAT can mis-prime the NAT mapping and break the hole punch.

## RPCS3: `p2ps-disconnect-fix.patch`

Modifies `rpcs3/Emu/Cell/lv2/sys_net/lv2_socket_p2ps.cpp`,
`rpcs3/Emu/NP/signaling_handler.cpp`, `rpcs3/Emu/NP/signaling_handler.h`,
`rpcs3/Emu/NP/np_cache.cpp`, `rpcs3/Emu/Cell/Modules/sceNp.cpp`, and
`rpcs3/Emu/Cell/Modules/sceNp2.cpp`.

Each P2PS stream is a TCP-over-UDP connection between two peers; RPCN provides
only the signaling, never relaying the data. When a player stopped responding,
RPCS3's P2PS layer used to let the whole lobby hang. This patch detects the
timeout and queues a forced disconnect on the client side, so the dropped player
is cleaned up locally and the remaining players keep playing.

What it changes:

- A dead stream is reported to the game instead of hidden. A read on a
  disconnected stream returns `ECONNRESET` rather than the zero-length read a
  game loop spins on, and `poll` reports `POLLHUP`, so a title waiting on the
  dropped peer stops waiting.
- The signaling status getters (`sceNpMatching2SignalingGetConnectionInfo` and
  `sceNpSignalingGetConnectionInfo`) report a timed-out peer as gone rather than
  still connected, so a title that polls them observes the drop.
- The retry path uses RFC 6298 round-trip estimation with exponential backoff and
  a retry cap; on timeout it hands the dead endpoint to the signaling thread,
  which marks the peer inactive and closes the local stream.
- The room cache drops a departed member correctly, so a left player no longer
  lingers as an empty occupied slot.

An earlier attempt at this disconnect handling introduced a lock-order deadlock:
callbacks and packets were dispatched while the signaling handler held its state
lock, so a peer teardown could cross with a concurrent socket operation taking
the same locks the other way. This patch handles the disconnect in a thread-safe
manner: the handler records callbacks and packets while the lock is held and runs
them after releasing it, and the timeout monitor hands the disconnect to the
signaling thread rather than reaching into that lock itself, so neither side
holds one domain's lock while taking the other's.

## RPCS3: `np-freeze-tracer.patch`

Adds `rpcs3/Emu/NP/freeze_tracer.h` and probes in `signaling_handler.cpp`,
`lv2_socket_p2ps.cpp`, `sceNp.cpp`, `sceNp2.cpp`, and `cellSysutil.cpp`.

Pure-observation diagnostics for the lobby-disconnect freeze. Every probe is a single
relaxed atomic counter bump; nothing changes control flow, locking, timing, or return
values, so the build stays functionally identical to the one without it. It exists to
make a recurrence self-describing from the log instead of needing a live repro.

What it records:

- Two heartbeats: one bumped at the top of the signaling handler loop, one in
  `cellSysutilCheckCallback` (the game's callback pump). The P2PS `tcp_timeout_monitor`,
  which never takes the signaling state lock, reads both and logs an edge-triggered
  `[freeze-tracer]` warning when either stops advancing for a few seconds, plus a second
  warning when it resumes. A stalled pump with a live signaling thread and a stalled
  signaling thread point at different causes.
- Enqueue/deliver counters for the Dead and Established signaling callbacks (enqueued
  under the state lock, delivered after it is released). When signaling stalls, the
  monitor logs the four counters once; enqueued greater than delivered indicates the
  callback pump is wedged rather than the signaling thread.
- Per-second call-rate logging for the three connection-info / room-member getters, so a
  title busy-polling a peer we report as gone is distinguishable from a blocked wait.

All logging is rate-limited or edge-triggered, so a healthy session stays quiet. The
counters live in one header included by each touched translation unit.

## RPCS3: `lv2-cond-tracer.patch`

Adds cond-variable tracing in `rpcs3/Emu/Cell/lv2/sys_cond.cpp`, a trigger in
`lv2_socket_p2ps.cpp`, and an arming flag in `rpcs3/Emu/NP/freeze_tracer.h`.

A follow-on to `np-freeze-tracer.patch`, kept separate so it can be dropped on its own.
Also pure observation, and inert in normal play: it does nothing until the freeze-tracer
stale-watcher detects the signaling thread has stopped making progress.

When that happens the P2PS monitor arms a flag and takes a read-only snapshot of every PPU
thread parked on an lv2 condition variable (walked through `idm` under its own read lock),
logging each one with its cond id and game instruction address; it repeats the snapshot
about ten seconds later, so a thread sitting on the same cond at the same address in both
snapshots is genuinely stuck rather than mid-handoff. While the flag is armed, the three
`sys_cond` signal syscalls log the cond id, the signaling thread, and its instruction
address, which records who would have released each wait. The flag is cleared when progress
resumes. With the flag clear the only cost in those syscalls is one relaxed atomic-flag
read, so a healthy session is unaffected.

## RPCS3: `fps-unlock.patch`

Modifies `rpcs3/Emu/Cell/PPUModule.cpp`, `rpcs3/Emu/Cell/PPUThread.cpp`,
`rpcs3/Emu/Cell/lv2/sys_ppu_thread.cpp` and `rpcs3/Emu/RSX/RSXThread.cpp`.

The game was built for 30fps and several parts of it advance by a fixed step per
rendered frame rather than by elapsed time, so raising the frame rate makes those
parts run proportionally fast. This patch makes the frame-rate-coupled parts behave
the same at any rate, which is what lets the launcher's FPS Mode raise it.

Four fixes, each a no-op for any other title. Three are installed from
`ppu_load_exec`; the movie fix needs no install and watches the `sys_ppu_thread`
syscalls directly:

- **Engine cutscenes.** Their timeline advances per rendered frame with no
  delta-time scaling, so above the native rate they play fast, and the pre-match
  cutscene ends early for the player running unlocked. The timeline clock is not
  reachable from the PPU side, so a call inside the cutscene update, which runs once
  per rendered frame and is silent everywhere else, is redirected through a thunk
  that timestamps the tick. While those ticks are fresh the vblank rate is held at
  the native value.
- **Pre-rendered movies.** The middleware paces its own decoding, but the game draws
  the subtitles on the ordinary per-frame tick, so above the native rate they run
  ahead of the audio. The decode thread's lifetime is watched at the `sys_ppu_thread`
  create and exit syscalls, which needs no guest address and does not move between
  game versions, and the same native-rate hold applies while it lives.
- **Thrust.** The flight model's per-frame speed update scales its thrust term by the
  frame delta but applies two threshold-gated correction terms as a fixed step per
  call. Calling the update more often therefore accumulates those two faster than the
  scaled term, and acceleration to top speed takes about half as long at twice the
  frame rate. The whole update is wrapped at its entry and its single exit, and its
  net per-call change is rescaled by the frame-step ratio. At the native rate the
  ratio is 1.0 and the wrapper is a bit-exact pass-through.
- **Vertical sink.** The same shape without an accumulator: a per-frame correction to
  vertical velocity that is not delta-scaled, so an aircraft sinks proportionally
  faster the higher the frame rate. The single instruction is scaled in place.

All four redirect guest instructions through `ppu_form_branch_to_code` and the
faux-block registry, which the LLVM translator honours where `ppu_breakpoint` does
not. Each installer verifies the instruction it is about to redirect, so a build whose
bytes differ is declined rather than patched blindly. Contributed by VF0S-D.

The vblank loop also gained a per-iteration rate check. It previously refreshed the
rate only at a period boundary, so a forced native rate could persist indefinitely
after the cutscene that asked for it had ended.

## rpcn: `tss-server.patch`

Modifies `src/server.rs` and `servers.cfg`, and adds `src/server/tss_server.rs`.

### TSS HTTP server module

The new file `src/server/tss_server.rs` defines a small `hyper`-based HTTP
server bound to `<host>:<rpcn_port + 2>` (same offset convention as the stat
server, which uses `port + 1`). It serves:

```
GET /tss/<com_id>/<filename>
```

from `tss_data/<com_id>/` on disk. Path-traversal characters (`..`, `/`, `\`)
in either segment return 400. Missing files return 404. Non-GET methods return
405. Started from `Server::start_tss_server`, called between the UDP and stat
servers in `Server::start`. Uses the existing `TerminateWatch` channel for
shutdown.

### `servers.cfg` entries

Five lines added for the game's community ID, registering worlds 1 through 5 each at
`worldId = 65537`. These satisfy the game's matchmaking world-list request.
Combined with the RPCS3-side padding above, the game sees the minimum list
length it expects.

## RPCS3: `rpcn-disconnect-fix.patch`

Modifies `rpcs3/Emu/NP/np_cache.cpp`, `rpcs3/Emu/NP/np_cache.h`,
`rpcs3/Emu/NP/np_handler.cpp`, `rpcs3/Emu/NP/rpcn_client.cpp`,
`rpcs3/Emu/NP/rpcn_client.h`, and `rpcs3/Emu/NP/np_requests.cpp`.

Two RPCN-link recovery changes, both contributed by VF0S-D and previously
carried as separate patches (`rpcn-reconnect.patch` and
`rpcn-roomdata-notfound-fix.patch`).

### Auto-reconnect after a dropped RPCN link

Adds an auto-reconnect loop in `np_handler::operator()` (the RPCN polling
thread). When `is_psn_active` is set but `rpcn->is_connected()` is false after
authentication has been established, the loop waits a short grace period then
calls `rpcn->prepare_reconnect()` on the existing client object and
re-runs `wait_for_connection()` / `wait_for_authentified()` / `get_addr_sig()`
with progressive backoff. A new `prepare_reconnect()` method on `rpcn_client`
(and its declaration in the header) resets the client's socket/SSL state and
clears the sticky error flag so those entry points re-execute their login path
rather than returning the cached failure. A new `cache_manager::has_active_rooms()`
helper (and its declaration in `np_cache.h`) lets the loop distinguish
single-player from in-room play and apply different patience: single-player
retries quietly indefinitely; in-room play retries for up to 5 minutes before
going offline.

Reported symptom: RPCN link drops after approximately 10 minutes under some
VPN configurations (issue #8). Hardened before landing: the original
`rpcn.reset()` / `rpcn_client::get_instance()` recreation (a weak_ptr
resurrection race) was replaced with the in-place `prepare_reconnect()` call.
The root cause of the link drop (why UDP traffic
stops ~10 min into a session under some VPN setups) has not been identified;
this works around it at the reconnect layer. Tested by the contributor on
their VPN setup; not reproduced or validated independently in-house.

### Room-data NotFound after a disconnect

Maps `rpcn::ErrorType::NotFound` to `SCE_NP_MATCHING2_SERVER_ERROR_NO_SUCH_ROOM`
in four matching2 room reply handlers: `reply_set_roomdata_external`,
`reply_get_roomdata_internal`, `reply_set_roomdata_internal`, and
`reply_send_room_message`. Each already handles `rpcn::ErrorType::RoomMissing`
with the same mapping; previously `NotFound` fell through to
`fmt::throw_exception`, a fatal emulator stop.

After a player disconnects, the server removes their room, so the game's
end-of-match room-data calls (the results/reward screen) receive `NotFound`
and crash. Returning a normal `NO_SUCH_ROOM` lets the game handle the missing
room gracefully and continue to its progression save instead of crashing.
Symptom: disconnected players crash on the reward screen and lose progression;
with the patch they save normally. Contributed by VF0S-D (contributor-tested;
exact game-side handling not reverse-engineered).

## RPCS3: `matchrate-range-fix.patch`

Modifies `rpcs3/Emu/NP/rpcn_client.cpp`.

The game's Create Room screen offers a Matching Rate Range (Narrow, Standard,
Wide, No Restrictions), which declares a skill-rating window on the room. The two
ends of that window travel as searchable int attributes `0x4d`
(`SCE_NP_MATCHING2_ROOM_SEARCHABLE_INT_ATTR_EXTERNAL_2_ID`) and `0x4e`
(`..._EXTERNAL_3_ID`). A searching client sends its own rating back as `<=` and
`>=` conditions on the same pair, and the matching server drops any room whose
window excludes it. No Restrictions sends `[0, INT32_MAX]`; Standard, the default,
sends a narrow band around the host's current rating. On a small player base that
makes a host unfindable by most of the people searching, and nothing the searcher
does can widen it.

The patch overrides those two values where the outgoing request is built, so the
room always advertises `[0, INT32_MAX]`. Both `createjoin_room` and
`set_roomdata_external` need it: the game re-sends the attributes seconds after
every room creation, and again after each match, so overriding room creation alone
is undone almost immediately. The in-game setting is untouched, the host still
sees and picks any of the four options, and only the values on the wire change.
Gated to `NPUB31347`, because the two attribute slots are generic and other titles
put unrelated values in them. Each override logs to the `rpcn` channel, so a user
log shows whether it ran. Contributed by VF0S-D.

## RPCS3: `additional-tree-transparency-fixes.patch`

Modifies `rpcs3/Emu/RSX/VK/VKDraw.cpp` and `rpcs3/Emu/RSX/GL/GLDraw.cpp`.

The game builds its distant-tree impostors as gather-assembled texture atlases
(`deferred_request_command::mipmap_gather`). The source render-target surfaces are not
reliably resident when those atlases are sampled, so the upper mip levels come back black
and distant billboards turn into black squares. The patch clamps sampling to mip 0 for
gather-assembled textures only, leaving CPU-uploaded textures such as buildings and
terrain untouched. Both renderers. Replaces an earlier Vulkan-only version of the same
fix rather than stacking on it. Contributed by VF0S-D.

## RPCS3: `terrain-mesh-mismatch-experimental-fix.patch`

Modifies `rpcs3/Emu/RSX/Program/GLSLCommon.cpp`.

Adds a half-texel offset to the `VERTEX_TEXTURE_FETCH2D` codegen so the vertex heightmap
fetch samples texel centres, correcting a terrain mesh misalignment. Marked experimental
in the patch itself: it changes every vertex texture-fetch 2D user, not only this game,
and it has not been validated against other titles. Contributed by VF0S-D.

## RPCS3: `gl-pointsprite-coord-origin.patch`

Modifies `rpcs3/Emu/RSX/GL/GLGSRender.cpp` and `rpcs3/Emu/RSX/GL/GLProcTable.h`.

Sets `GL_POINT_SPRITE_COORD_ORIGIN` to `GL_LOWER_LEFT` in one-time GL state setup, and
registers `glPointParameteri`, a GL 1.4 entry point that the Windows `opengl32` GL 1.1
export set does not carry. The GL backend renders the scene Y-flipped to reconcile GL's
bottom-left window origin with the RSX's top-left, but never set the point-sprite origin,
so every sprite using `COORD_REPLACE` sampled its texture upside down and appeared to roll
with the camera. OpenGL only; Vulkan has no scene flip and was already correct.
Contributed by VF0S-D, tested on NVIDIA.

## RPCS3: `pointsize-resolution-scale.patch`

Modifies `rpcs3/Emu/RSX/GL/GLVertexProgram.cpp`, `rpcs3/Emu/RSX/GL/GLGSRender.cpp`,
`rpcs3/Emu/RSX/VK/VKVertexProgram.cpp`, `rpcs3/Emu/RSX/VK/VKGSRender.cpp`,
`rpcs3/Emu/RSX/VK/VKShaderInterpreter.cpp`, and the two shader sources
`Program/GLSLSnippets/RSXProg/RSXDefines2.glsl` and
`Program/GLSLInterpreter/VertexInterpreter.glsl`.

Multiplies program-generated `gl_PointSize` by the resolution scale factor in all four
codegen paths (GL and Vulkan, recompiler and interpreter). The fallback
`NV4097_SET_POINT_SIZE` path is already pre-scaled when the buffer is filled and is left
alone, so nothing scales twice. `point_size_scale` goes into the reserved slot at byte 84
of `vertex_context_t`, so the 96-byte stride is unchanged. Without it, foliage sprites
shrink at any resolution scale above 100% and, being centre-anchored, lift off the terrain
and lose their trunks. Contributed by VF0S-D.

This is the one patch in the series that keeps CRLF line endings, because the two `.glsl`
files it edits are CRLF in the upstream blobs. `.gitattributes` carries a `-text` exception
for it; without that the file normalises to LF and then fails on a fresh checkout while
still applying in the working copy that produced it.

## Applying and resetting

```
SRC\apply-patches.bat
```

Runs `git apply` against both submodules. Fails if either working tree isn't
clean.

```
SRC\reset-git-repos.bat
```

Runs `git reset --hard HEAD` and `git clean -ffdx` on both submodules,
restoring them to the pinned commits and removing patch-introduced files
(including the new `tss_server.rs`).
