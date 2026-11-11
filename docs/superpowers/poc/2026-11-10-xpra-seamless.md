# Xpra seamless GUI proof of concept

**Result:** Narrow transport and display proof passed; not a product feature or
security certification.  
**Date:** 2026-11-10  
**Environment:** Fedora 44 x86_64, X11 `:0`, dwm; Docker Engine 29.9.2 through
the dedicated `haibox` context.

## What was tested

A temporary Fedora 44 image contained Xpra 6.5.4, xterm 411, Xvfb 21.1.25,
socat 1.8.1, and Python GObject. A HAIBOX-managed empty-scope engagement ran
that image with the existing `core` profile's container constraints. Its Xpra
server listened on `127.0.0.1:14500` inside the container. A temporary host
relay listened only on `127.0.0.1:14501`, launched a non-TTY
`docker exec --interactive` process, and bridged the byte stream to the Xpra
server over container loopback. There were no published Docker ports.

The host's Xpra 6.5.4 client was extracted from the Fedora RPM into a temporary
directory and run without installing any package on Fedora. Xpra authenticated
with a random session password file stored in container `/tmp` and a host-side
mode-0600 temporary file. No password, host display socket, or host Xauthority
file was mounted into the container.

The relay was a test harness, not production HAIBOX code. It was hard-coded to
one managed container. The current HAIBOX CLI's audited `run` command launched
the server setup and xterm; no `haibox gui` commands or runtime changes were
made.

## Results

| Check | Result |
|---|---|
| Xpra stream over Docker Exec | **Passed.** The native client reported “Attached to xpra server at tcp://127.0.0.1:14501/”; the server reported Xpra 6.5.4 and bound only to container loopback. |
| Native host window | **Passed.** DWM's `wmctrl -l` listed `HAIBOX Xpra PoC on haibox-gui-poc` while the process table in the engagement showed `xterm` running as UID 1000. |
| Multiple windows | **Passed.** Two independent xterm processes appeared as two DWM-managed windows in the same Xpra session. |
| Authentication | **Passed.** A wrong password returned exit 28 with “Authentication failed.” After stopping and restarting Xpra with a new random password, the old session credential was rejected and the new credential attached. |
| Disconnect/reconnect | **Passed.** Detaching hid the remote windows but kept the Xpra server and xterm processes running; reconnect restored the window. |
| Stop/restart and workspace | **Passed.** `xpra stop` shut down the Xpra server, Xorg, and xterm. The HAIBOX container stayed running. A marker under `/workspace` remained after restarting the Xpra server. |
| Container hardening | **Passed.** Docker inspection showed non-root `1000:1000`, `ReadonlyRootfs=true`, `Privileged=false`, private IPC, `CapDrop=["ALL"]`, no added capabilities, no devices, empty port bindings, and only workspace RW plus scope RO mounts. |
| Display and Docker socket exposure | **Passed.** The container had no `/var/run/docker.sock`, host `/tmp/.X11-unix/X0`, or host `/run/user/1000/wayland-0`; no host `DISPLAY`, `WAYLAND_DISPLAY`, or `XAUTHORITY` was present. The app used the headless container display `:100`. |
| Fedora SSH service | **Blocked as expected.** The runner had only `172.19.0.0/16` connected and no default route. Connections to host LAN `192.168.1.34:22` and Docker bridge `172.17.0.1:22` failed with `Network is unreachable`; Fedora's SSH daemon was listening on port 22. |
| Cross-engagement access | **Blocked as expected.** A Python HTTP server was confirmed listening on `0.0.0.0:18080` in a second managed engagement (`172.20.0.1`); the GUI engagement could not route to it. |
| Port publishing | **Passed.** `HostConfig.PortBindings` was `{}`; no Docker port was published. |

The temporary image ID was
`sha256:6bad2d1c3afba55fb66fc55f7786bd86f8576520427170fc6c101dfbe6c84816`
and measured 1,163,045,221 bytes. DNF installed 233 packages (about 628 MiB
additional installed data before the final small GObject layer) to satisfy the
Fedora Xpra package's desktop and multimedia dependencies. This test image was
not added to the catalog and was not scanned; do not infer a vulnerability
status from a successful window test.

A reproducible fixture is recorded at
[`gui-image/Dockerfile`](gui-image/Dockerfile). It pins the Fedora 44 base digest
and the same direct package versions. A 2026-11-11 rebuild produced
`sha256:41d34aad54acd6282598d5656f6ee91967fb60b13537dffdd2e3e99acb220c43`
at 1,399,669,162 bytes with 502 RPMs. Trivy 0.76.2 reports that Fedora is an
unsupported OS and returns no vulnerability results. That is not a clean scan;
see the [image validation record](2026-11-10-gui-image-validation.md) for the
blocking gate and the Debian packaging check.

## Limits and failed experiments

- This proves Xpra 6.5.4 TCP protocol bytes can cross a Docker Exec stdio relay
  and produce native windows on this Fedora 44 X11/dwm session. It is not an
  Xpra-supported Docker transport, a general distro-compatibility result, or a
  Wayland test. Only Fedora was tested; Arch and other distributions remain
  unverified.
- The local relay did not implement dynamic engagement selection or test
  cross-engagement relay authorization. Network isolation between two
  engagements was tested, but production CLI identity checks and relay
  lifecycle still need design and negative tests.
- The test did not test clipboard/file transfer/audio/device forwarding through
  active misuse. Both server and client were launched with clipboard,
  file-transfer, printing, speaker, microphone, webcam, notifications, system
  tray, DBus controls, and server-side command execution disabled. Production
  defaults still need automated config assertions.
- An optional Python GTK window failed because the temporary image lacked the
  `xlib-2.0` introspection typelib. The two xterm windows passed; this failure
  shows that GUI app images need explicit, application-specific runtime
  dependencies.
- Burp Suite and a browser were not installed or tested. PortSwigger's
  Community terms require the user to accept its license and restrict
  redistribution. Burp binaries must stay out of a public HAIBOX image pending
  the user's own installer and license acceptance; see the [vendor research](../research/2026-11-10-desktop-vendor-research.md#burp-suite-community-edition).
- No screenshot was captured. The native window was verified from the live
  Fedora window manager (`wmctrl -l`) and the matching in-container process.
- This PoC does not test Docker/kernel escape resistance, hostile Xpra protocol
  inputs, host Xpra client vulnerabilities, M2 scope enforcement, external
  target routing, or behavior on other Docker implementations/platforms.

The GUI session used the `isolated` network only. Do not use `scoped` for
external targets: HAIBOX M2 scope enforcement remains a forward-only prototype
and does not yet cover host services or embedded DNS.

## Cleanup

The second engagement was destroyed through `haibox engagement destroy
--force --yes`. The remaining PoC engagement and network were also destroyed
through the HAIBOX CLI. The temporary host Xpra client extraction, relay,
password files, workspace, build context, and image were removed. No Docker
daemon, firewall, SELinux policy, Fedora service, or unrelated project was
changed.
