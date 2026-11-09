# Runbook: optional dedicated KVM VM

> **Optional deployment.** HAIBOX runs directly on Fedora with Docker. This
> runbook is for operators who want a stronger boundary for high-risk
> engagements or a disposable lab. It is not a prerequisite for development,
> unit tests, image builds, or ordinary Docker use.

## 1. Purpose and boundary

The VM is an optional high-assurance deployment profile. When used, it is
dedicated to HAIBOX: no personal files, no unrelated services, no reused
credentials, and no other Docker workloads. The Fedora workstation remains a
general-purpose host, so running engagement containers there puts it inside
the trust boundary; the VM removes it.

The VM may be destroyed and rebuilt after an engagement. Treat it as
disposable; keep only the source repository and approved evidence exports on
the host.

## 2. Specification

| Item | Recommended | Minimum | Notes |
|---|---|---|---|
| VM name | `haibox-lab` | same | One VM per operator |
| Guest OS | Debian 13 (trixie) amd64 | Debian 12 | Minimal, no desktop |
| vCPU | 8 | 4 | Host needs 2–4 for itself |
| RAM | 16 GiB | 8 GiB | Web Security tools are memory-hungry |
| Disk | 120 GiB qcow2 | 80 GiB | Thin-provisioned; monitor free space |
| Swap | 4 GiB | 2 GiB | Inside the guest |
| Firmware | BIOS (SeaBIOS) | same | UEFI/Secure Boot optional later |
| CPU model | `host-passthrough` | `host-model` | Needed for performance; nested virt optional |
| Graphics | none (serial console) or VNC during install | same | SSH after install |
| NIC 1 | libvirt `default` NAT | same | Management and package updates |
| NIC 2 | libvirt `haibox-ops` isolated | optional | Target VMs or physical lab |
| Host disk | SSD/NVMe, LUKS-encrypted | same | Do not use a network share |
| Snapshots | before upgrades and before each engagement | same | Keep at least one clean snapshot |

### Host prerequisites

- x86_64 CPU with VT-x (`vmx`) or AMD-V (`svm`) enabled in firmware.
- At least 8 logical CPUs and 32 GiB RAM recommended (4 CPUs / 16 GiB minimum).
- At least 200 GiB free on an SSD for the VM, snapshots, and images.
- Wired network preferred; Wi-Fi works but is less reliable for long scans.
- Fedora packages: `libvirt-daemon-kvm`, `qemu-kvm`, `virt-install`,
  `libvirt-client`, and optionally `virt-manager`, `virt-viewer`.
- The operator is in the `libvirt` group (host-side convenience only).

## 3. Network design

```text
Fedora host
├── virbr0 (libvirt default, NAT)      192.168.122.0/24
│   └── haibox-lab enp1s0             192.168.122.50/24, gw .1, DNS .1
│       └── package updates, SSH from host
│
├── virbr-ops (libvirt isolated)       10.66.0.0/24, no forward
│   ├── haibox-lab enp2s0             10.66.0.10/24, no gateway, no DNS
│   └── target VMs (optional)          10.66.0.100-199 via DHCP
│
└── (future) VPN gateway inside the VM, over the management NIC
```

### Rules

1. The management NIC is the only route to the internet. It is used for
   package updates, source checkout, image builds, and SSH from the host.
2. The operations NIC has **no default gateway and no DNS**. It carries only
   target traffic. The HAIBOX VM must not use it for updates or management.
3. The `haibox-ops` libvirt network has `<forward mode='none'/>`; the Fedora
   host firewall must drop traffic on `virbr-ops` except DHCP/DNS if target VMs
   need it. The host must not route between `virbr0` and `virbr-ops`.
4. No libvirt port forwarding to the VM. SSH is reached from the host over
   `virbr0` only.
5. Docker runner networks use `--internal` plus Docker's `isolated` gateway
   mode, so the VM host has no address on the bridge. They use the
   `10.200.0.0/16` address pool and never attach to `virbr0` or `virbr-ops`.
   The legacy `internal` profile was removed (ADR-0009).
6. IPv6 is disabled in the guest unless an engagement explicitly requires it.
   If it is enabled, the firewall must default-deny IPv6 from runner bridges.
7. The future VPN gateway is the only component allowed to route runner traffic
   off the VM. It must fail closed when the tunnel drops.

### Why not attach runners directly to `virbr-ops`?

A Docker bridge attached to a libvirt network would give every runner a route
to the target network and to the VM's host stack. The design keeps runners on
isolated internal bridges and puts the controlled path (VPN gateway or a future
scope router) in front. This is not implemented yet; the MVP runner has no
external route and no host gateway.

## 4. Guest disk layout

Use LVM so Docker data and private data can be snapshotted or quota-limited
later.

| Mount | Size | Filesystem | Purpose |
|---|---|---|---|
| `/` | 30 GiB | ext4 | OS and packages |
| `/var` | 55 GiB | ext4 | Docker images, containers, logs |
| `/srv` | 20 GiB | ext4 | Future vault and exports |
| `/home` | 11 GiB | ext4 | Operator account and source checkout |
| swap | 4 GiB | swap | Hibernation not needed |

Adjust to the disk size. Keep at least 15% free.

## 5. Host preparation (after approval)

Run these on the Fedora host if you choose the VM profile. They are listed for review; they are not executed
by this repository.

```bash
# Read-only preflight
lscpu | grep -E 'Virtualization|vmx|svm'
free -h
df -h /var/lib/libvirt
lsmod | grep kvm
virsh list --all
virsh net-list --all
docker context ls

# Install the virtualization stack (requires sudo)
sudo dnf install -y libvirt-daemon-kvm qemu-kvm virt-install libvirt-client virt-viewer
sudo systemctl enable --now libvirtd
sudo usermod -aG libvirt "$USER"
```

Log out and back in for the group change. Then define the isolated operations
network:

```bash
cat >/tmp/haibox-ops.xml <<'XML'
<network>
  <name>haibox-ops</name>
  <bridge name='virbr-ops' stp='on' delay='0'/>
  <forward mode='none'/>
  <ip address='10.66.0.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='10.66.0.100' end='10.66.0.199'/>
    </dhcp>
  </ip>
</network>
XML

sudo virsh net-define /tmp/haibox-ops.xml
sudo virsh net-start haibox-ops
sudo virsh net-autostart haibox-ops
```

Host firewall requirements (implement with the host's firewall manager, not
ad hoc `iptables` commands that disappear on reboot):

- allow DHCP/DNS on `virbr-ops` only if target VMs need it;
- drop forwarding between `virbr-ops` and `virbr0`;
- drop forwarding between `virbr-ops` and the host's physical interfaces;
- allow SSH to `192.168.122.50` from the host only;
- no inbound port forwards to the VM.

## 6. Create the VM

Download the Debian 13 netinst ISO and verify its signature against the Debian
signing keys. Then:

```bash
sudo virt-install \
  --name haibox-lab \
  --memory 16384 \
  --vcpus 8 \
  --cpu host-passthrough \
  --disk path=/var/lib/libvirt/images/haibox-lab.qcow2,size=120,format=qcow2,bus=virtio,cache=none,io=native,discard=unmap \
  --network network=default,model=virtio \
  --network network=haibox-ops,model=virtio \
  --graphics none \
  --console pty,target_type=serial \
  --location /var/lib/libvirt/images/debian-13-netinst.iso \
  --extra-args 'console=ttyS0,115200n8' \
  --os-variant debian13 \
  --noautoconsole
```

If serial installation is awkward, use `--graphics vnc,listen=127.0.0.1` and
`virt-viewer --connect qemu:///system haibox-lab` for the installer, then
switch to SSH. Do not expose VNC on a public interface.

### Installer choices

- hostname `haibox-lab`; domain empty;
- root password disabled; create user `haibox` with a strong password and an
  SSH key;
- guided LVM partitioning per §4;
- no desktop environment; install `SSH server` and `standard system utilities`;
- UTC timezone;
- Debian mirror over the management NIC.

### First boot

```bash
# On the guest console
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y sudo curl ca-certificates gnupg git jq nftables \
  unattended-upgrades chrony openssh-server rsync make
sudo systemctl enable --now nftables chrony unattended-upgrades
```

Configure static addressing for the operations NIC. Identify it with `ip link`
(it is the second virtio NIC, usually `enp2s0`):

```bash
# /etc/network/interfaces.d/ops
auto enp2s0
iface enp2s0 inet static
    address 10.66.0.10/24
    # no gateway, no dns-nameservers
```

Bring it up with `sudo ifup enp2s0`. Verify:

```bash
ip -4 addr show enp2s0
ip route            # must NOT contain a default route via enp2s0
ip -6 addr show     # IPv6 should be absent unless explicitly enabled
```

If the guest has IPv6 on the management NIC and it is not needed, disable it
persistently and verify that package updates still work:

```bash
# /etc/sysctl.d/99-haibox-no-ipv6.conf
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
```

## 7. Guest hardening

### SSH

```bash
sudo install -d -m 0700 /home/haibox/.ssh
# add the operator public key to /home/haibox/.ssh/authorized_keys
sudo chown -R haibox:haibox /home/haibox/.ssh
sudo chmod 0600 /home/haibox/.ssh/authorized_keys
```

`/etc/ssh/sshd_config.d/99-haibox.conf`:

```text
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AllowUsers haibox
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
```

Restart SSH and verify from the host before closing the console.

### Firewall

Use nftables with a default-deny inbound policy. The exact rules depend on
whether target VMs use DHCP/DNS on `virbr-ops`. At minimum:

- allow established/related;
- allow SSH from `192.168.122.1` (host) only;
- allow outbound DNS/HTTP/HTTPS on the management interface;
- drop inbound from `virbr-ops` to host services;
- drop forwarding between `virbr0`, `virbr-ops`, and Docker bridges;
- drop IPv6 unless explicitly enabled.

Record the final ruleset in the VM and export it with the M1 evidence.

## 8. Docker installation

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker haibox
```

Log out and back in. Create the dedicated context:

```bash
docker context create haibox --docker host=unix:///var/run/docker.sock
docker context inspect haibox
docker --context haibox version
```

Do **not** export `DOCKER_HOST` or `DOCKER_CONTEXT` in the operator shell; the
CLI passes `--context haibox` explicitly.

`/etc/docker/daemon.json` (review before applying; restart Docker after):

```json
{
  "icc": false,
  "iptables": true,
  "ip6tables": true,
  "ip-forward": true,
  "userland-proxy": false,
  "live-restore": true,
  "log-driver": "local",
  "log-opts": {"max-size": "10m", "max-file": "3"},
  "default-address-pools": [
    {"base": "10.200.0.0/16", "size": 24}
  ]
}
```

Notes:

- `icc: false` affects the default bridge; each engagement uses its own
  user-defined internal network.
- `ip6tables: true` is defensive. If IPv6 is disabled in the guest, Docker
  will not create IPv6 networks.
- `default-address-pools` keeps engagement networks out of the management and
  operations ranges.
- The VM is dedicated; the `docker` group is still root-equivalent. Do not add
  unrelated users.

## 9. Install the platform

```bash
# As haibox, on the VM
curl -LsSf https://astral.sh/uv/install.sh | sh
# or pin a reviewed version:
# pipx install uv==0.13.5

uv python install 3.12

# Copy the source tree from the host (or clone a private remote)
rsync -av --exclude .venv --exclude .git \
  /path/to/haibox/ haibox@192.168.122.50:/home/haibox/haibox/

cd /home/haibox/haibox
uv sync --extra dev --python 3.12
uv run pytest
uv run ruff check .
uv run mypy src
```

Do not proceed if any of these fail. Capture the output in the M1 evidence.

```bash
uv run haibox init
uv run haibox doctor
uv run haibox image build web-security
uv run haibox image verify web-security
```

Optional scanner (install only after reviewing the vendor instructions):

```bash
# Example: trivy from its official repository or a verified release binary
uv run haibox image scan web-security
```

## 10. Integration test

```bash
HAIBOX_RUN_INTEGRATION=1 uv run pytest -m integration -vv
```

The test creates one engagement, one internal network, and one container, then
checks the isolation shape and removes everything. If it fails, preserve the
VM snapshot and the audit logs before retrying.

## 11. Manual verification

Create a disposable engagement:

```bash
uv run haibox engagement init smoke \
  --name "Smoke test" \
  --profile web-security \
  --target 10.66.0.100 \
  --allowed-port 443

uv run haibox shell
```

Inside the runner:

```bash
id -u                                  # non-zero
ip route                               # no default route
getent hosts example.com                # expected to fail
curl --max-time 3 http://192.168.122.1 # expected to fail
curl --max-time 3 http://169.254.169.254 # expected to fail
ip -6 route                            # empty or no default
test -w /etc/haibox/scope.json        # expected to fail
touch /workspace/.smoke                # expected to succeed
ls /evidence /reports 2>/dev/null      # expected to be absent
```

Record each result. A failure of an "expected to fail" check is a security
finding, not a test flake.

## 12. Snapshot and handover

From the host:

```bash
sudo virsh snapshot-create-as haibox-lab clean-m1 \
  "Debian 13, Docker, uv, unit tests green, image verified"
sudo virsh snapshot-list haibox-lab
```

Store the snapshot name, image digest, scan report, and security-checklist
results with the M1 evidence. Do not store client secrets in the snapshot.

## 13. Rebuild and rollback

- To roll back to the clean snapshot: shut down the VM, `virsh snapshot-revert
  haibox-lab clean-m1`, start it, and re-run `haibox doctor`.
- To rebuild: destroy the VM and repeat this runbook from §6. The source tree
  and approved evidence exports live on the host; the VM is disposable.
- Never restore a snapshot that contains credentials you no longer trust.

## 14. Open items before real engagements

- [ ] Network enforcement (ADR-0003) is implemented and tested.
- [ ] The separate vault identity exists (ADR-0002).
- [ ] Off-VM append-only backup for audit and evidence exists.
- [ ] Workspace disk quota exists.
- [ ] Image signing/SBOM exists.
- [ ] The security checklist in `threat-model.md` is fully recorded.
- [ ] The public name decision is made (ADR-0005).
