# Architecture decision records

| ADR | Title | Status |
|---|---|---|
| [0001](0001-dedicated-vm-and-runtime-seam.md) | Dedicated VM and a narrow runtime seam | Superseded by 0006 |
| [0002](0002-host-only-data-and-vault-identity.md) | Host-only data and a separate vault identity | Accepted; identity not implemented |
| [0003](0003-scope-enforcement-layers.md) | Scope enforcement in layers | Accepted; network layer not implemented |
| [0004](0004-defer-ai-and-vpn.md) | Defer AI and VPN until the manual lane is proven | Partially superseded by 0007 |
| [0005](0005-temporary-codename.md) | Keep "HAIBOX" as a temporary codename | Accepted |
| [0006](0006-direct-docker-on-fedora.md) | Run directly on Fedora; KVM is optional | Accepted |
| [0007](0007-vpn-management-scope.md) | VPN management is in scope; AI remains deferred | Accepted |
| [0008](0008-engagement-network-isolation-profile.md) | Isolated gateway mode for engagement networks | Accepted; decision 3 superseded by 0009 |
| [0009](0009-remove-legacy-internal-profile.md) | Remove the legacy internal network profile | Accepted |
| [0010](0010-scoped-connectivity-profile.md) | Scoped connectivity profile for authorized external targets | Proposed; not implemented |
| [0011](0011-gui-session-in-existing-runner.md) | Optional GUI sessions in the existing engagement runner | Proposed; prototype only |

An ADR is required for any change that weakens a security invariant listed in
`SECURITY.md`. Supersede an ADR with a new record; do not edit history.
