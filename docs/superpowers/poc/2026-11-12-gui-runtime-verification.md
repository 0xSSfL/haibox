# GUI runtime, adversarial testing, and desktop compatibility

**Status:** The runtime and the commands are implemented and verified; the GUI
is still disabled for the owner.  
**Date:** 2026-11-12  
**Scope:** Phases 2, 4, and 5 of the GUI production program.  
**Related:** [ADR-0011](../../../adr/0011-gui-session-in-existing-runner.md),
[plan](../../../superpowers/plans/2026-11-12-gui-production-program.md),
[image evidence](../../../superpowers/poc/2026-11-12-gui-image-security.md),
[prototype evidence](../../../superpowers/poc/2026-11-11-xpra-gui-readiness.md)

## What was built

`src/haibox/gui/` is the product-code runtime:

- `spec.py` — `GuiSessionSpec` and `GuiLimits`. The display, port, runtime
  directory, and the deny-by-default flag list are fixed values, the image must
  be the approved GUI image, and the limits are validated.
- `preflight.py` — the eligibility rules: `isolated` profile, empty external
  scope, canonical scope file equal to the engagement metadata, managed and
  engagement labels, running container, `HostConfig.NetworkMode` match, and
  exactly one network membership.
- `credentials.py` — mode-0600 credential files created with
  `O_EXCL`/`O_NOFOLLOW` inside a verified 0700 directory, with symlink and
  non-regular-file refusal.
- `session.py` — the lifecycle. The ownership check runs before any stop
  request, the previous server must be confirmed terminated before the runtime
  is reset or the credential replaced, a foreign Xpra server is never
  signalled, and the Xpra version must be a qualified one.
- `relay.py` — the local Unix-domain relay: 0700 directory, 0600 socket,
  `SO_PEERCRED` peer authentication, one client at a time, bounded copies, and
  a fixed container bridge command.

The runtime reaches the container only through the runtime seam, so the future
restricted broker can implement the same interface. No runtime method accepts a
user-supplied container command, and `ContainerSpec` is unchanged.

## Command gate

`haibox gui start|attach|stop|status` exists and is complete, but every
command refuses while the GUI image is *experimental*:

```text
error: the GUI is not enabled: the GUI image haibox/gui:0.1.0 is experimental,
not active; promote it in images/gui/manifest.yaml after the image gate is accepted
```

The gate is the catalog status of the GUI image. There is no experimental flag
and no environment variable that can bypass it; only the owner can promote the
image. `haibox doctor` reports the GUI state without failing, because the
capability is optional.

## Real-Docker lifecycle run

The runtime was exercised against a disposable engagement on the reviewed
`haibox` Docker context with the scanned GUI image
(`haibox/gui:0.1.0`, Xpra 6.5.6, Fedora 46).

| Check | Observed result |
|---|---|
| Container shape | `haibox-gui-real` on the isolated engagement network, non-root `haibox:haibox`, read-only root filesystem, `CapDrop=["ALL"]`, no published ports, workspace read-write, `scope.json` read-only |
| Prepare | The session started (server pid 61); the host credential file was created with mode 0600 and the container credential with mode 600 |
| Verify | The running server carried every deny-by-default flag and reported the expected display and bind address |
| Rotation | A second prepare replaced the credential and left exactly one server process (pid 278) |
| Foreign server | An Xpra server on the same display from a different runtime directory (pid 481) was refused: `another Xpra server owns display :100 (pids (481,)); refusing to stop a session that this engagement does not own`. The foreign server was still running afterwards: it was never signalled |
| Stop | The host credential was gone, the container runtime directory was absent, and no server was left |

### Two defects the real run found

Neither defect was visible in the unit tests or in the image scan; both were
found by running the code in a container.

**1. The image was missing the GObject introspection bindings.** The Xpra
server exits with `the python gobject introspection bindings are missing`
before it binds its display, so the image now installs
`python3-gobject-3.58.1-6.fc46` and the manifest verifies it.

**2. A lingering stop request killed the next session.** `xpra stop` waits
for a server socket to appear. When a stop request was left over from an
earlier attempt, it stayed alive inside the container and shut down the server
that the *next* prepare had just started — with the message `Shutting down in
response to client request`. The runtime now:

- never sends a stop request when no server is running;
- bounds the stop request inside the container as well
  (`timeout N xpra stop :100`), so it cannot outlive the request;
- reports the processes that are still waiting for a server, and terminates
  those before the runtime is reset.

The third defect the run exposed was in the relay: the copy path only handled
sockets, so bridging to the container's byte stream raised
`'_io.BufferedWriter' object has no attribute 'send'` and the client saw
`failed to receive anything, not an xpra server?`. The relay now copies with
`os.read`/`os.write` on the file descriptor, so both a Unix socket and a pipe
work, and the desktop check passes.

## Adversarial test matrix

`tests/unit/test_gui_adversarial.py` is the executable form of the Phase 5
requirements. All of it runs without Docker.

| Requirement | Test | Result |
|---|---|---|
| Hostile protocol stream | `test_relay_survives_a_hostile_byte_stream` | 1 MiB of random bytes from the client does not crash the relay; the relay stays usable |
| Truncated and stalled streams | `test_relay_stops_a_stalled_peer_after_the_idle_timeout` | A peer that never sends is dropped after the idle bound |
| Concurrent sessions | `test_relay_refuses_a_second_client` | The second client is closed instead of being served |
| Foreign peer | `test_relay_rejects_a_peer_with_a_different_user` | A peer that is not the relay's user is refused |
| Authentication and secret handling | `test_the_credential_never_appears_in_the_server_argv`, `test_the_credential_is_not_written_to_the_audit_log` | The credential is a file name in argv, never a value, and never reaches the audit log |
| Credential rotation and revocation | `test_a_rotated_credential_replaces_the_previous_value`, `test_a_revoked_credential_is_removed` | Rotation replaces the value in place; revocation removes the file and the read then fails |
| Cross-engagement isolation | `test_a_container_of_another_engagement_is_refused`, `test_an_extra_network_is_refused`, `test_a_non_isolated_engagement_is_refused`, `test_external_targets_are_refused` | Every deviation from the engagement's own isolated runner is refused |
| Container-label manipulation | `test_a_forged_engagement_label_is_refused`, `test_a_removed_managed_label_is_refused` | A forged or missing label is refused |
| Canonical scope file | `test_a_scope_file_that_does_not_match_the_metadata_is_refused` | Drift between the metadata and the mounted scope file is refused |
| Forwarding bypass | `test_every_forwarding_feature_is_denied_on_the_server`, `test_the_client_flags_mirror_the_server_flags`, `test_the_spec_cannot_be_widened_by_a_caller` | Clipboard, file transfer, printing, audio, webcam, notifications, DBus, and remote commands are denied on both ends, and the flag list cannot be emptied |
| Resource exhaustion | `test_the_limits_are_bounded` | CPU, memory, process, session, connection, and timeout bounds are validated and closed |

## Desktop compatibility

| Check | Result |
|---|---|
| Native window on the Fedora 44 X11 host | The extracted Fedora 44 Xpra 6.5.4 client attached to the Fedora 46 Xpra 6.5.6 server through the relay and produced a native `xterm` window on display `:0`. |
| Socket permissions on the host | The relay directory was 0700 and the socket 0600. |
| Host/server version matrix | Fedora 44 host client 6.5.4 against the Fedora 46 server 6.5.6: compatible, same 6.5 protocol series. The runtime refuses any server version outside `6.5`. |
| Real Wayland input | **Not verified.** The host runs X11 only, and the previous headless-Weston test proved surfaces, not input. A real Fedora Workstation Wayland session with input devices is required and is not available in this environment. |

### Wayland input qualification

Wayland input forwarding cannot be claimed from a headless compositor: without
a seat and input devices there is nothing to forward. Verifying keyboard,
pointer, focus, resizing, and reconnect behaviour needs a real Wayland
session. The options considered were:

- installing a Wayland session on the host — that changes the operator's
  desktop session and is out of scope for an image and runtime change;
- a nested compositor — it reproduces the earlier headless-Weston limitation,
  where surfaces appear but no input device exists;
- a virtual DRM device (`vkms`) — it needs a kernel module and root, which
  would modify host kernel state.

The qualification therefore stays open and is recorded as an external
requirement, not as a pass.

## Host client distribution

The host client is currently extracted from the Fedora RPM into a temporary
directory. Debian 12, Debian 13, and Ubuntu 24.04 all ship the Xpra 3.1
series, which is not compatible with the 6.5 server this runtime qualifies, so
there is no distribution package that pairs with the server today. Options for
the owner:

1. keep the manual RPM extraction and document it (current state);
2. publish a small, pinned host-client bundle next to the image;
3. wait for the distributions to package the 6.x series.

## Remaining findings

| Finding | Severity | Status |
|---|---|---|
| Real Wayland input is unverified | Medium | Open — external qualification (a real Wayland session with input devices) |
| The host client has no distribution package | Low | Open — owner decision between the three options above |
| The GUI image base is a pre-release snapshot | Medium | Open — the image must be rebuilt on the Fedora 46 stable release |
| The audit events cover the session lifecycle, not a per-attach event | Low | Open — an attach event is recorded by the CLI relay command, but the attach itself is not audited per client |
| No adversarial test drives a real Xpra protocol stream | Low | Open — the unit tests use a fake container; a real-Docker stream fuzzing pass is still missing |
