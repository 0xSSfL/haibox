---
hide:
  - navigation
  - toc
---

<div class="hero-container" markdown>

<div class="hero-badges">
  <span class="hero-pill"><span class="twemoji">{% include ".icons/material/tag.svg" %}</span> v0.1.0 Alpha</span>
  <span class="hero-pill pill-cyan"><span class="twemoji">{% include ".icons/material/shield-lock.svg" %}</span> Isolated Gateway</span>
  <span class="hero-pill"><span class="twemoji">{% include ".icons/material/account-lock.svg" %}</span> Non-root (UID 65534)</span>
  <span class="hero-pill pill-purple"><span class="twemoji">{% include ".icons/material/docker.svg" %}</span> Docker 28+ Direct</span>
  <span class="hero-pill"><span class="twemoji">{% include ".icons/material/scale-balance.svg" %}</span> MIT Licensed</span>
</div>

<h1 class="hero-title">Your Pentest Lab.<br>In a Box.</h1>

<p class="hero-subtitle">
  An isolation-first, manual-first penetration testing workstation.
  Dedicated per-engagement workspaces, pinned tool manifests, and tamper-evident audit logs.
</p>

<div class="hero-actions">
  <a href="user-guide.md" class="btn-primary">
    <span class="twemoji">{% include ".icons/material/rocket-launch.svg" %}</span> Get Started
  </a>
  <a href="#toolkits" class="btn-secondary">
    <span class="twemoji">{% include ".icons/material/view-grid.svg" %}</span> Explore Toolkits
  </a>
  <a href="https://github.com/0xSSfL/haibox" class="btn-secondary" target="_blank" rel="noopener">
    <span class="twemoji">{% include ".icons/fontawesome/brands/github.svg" %}</span> View on GitHub
  </a>
</div>

<div class="quick-install-box">
  <div class="quick-install-code">
    <span class="prompt">$</span>curl -fsSL https://0xssfl.github.io/haibox/install.sh | bash
  </div>
</div>

</div>

<!-- Terminal Mockup -->
<div class="terminal-window">
  <div class="terminal-header">
    <div class="terminal-dots">
      <span class="terminal-dot close"></span>
      <span class="terminal-dot minimize"></span>
      <span class="terminal-dot zoom"></span>
    </div>
    <div class="terminal-title">haibox — engagement: demo (web-security)</div>
  </div>
  <div class="terminal-body">
    <div class="t-line"><span class="t-prompt">$</span> <span class="t-cmd">haibox engagement init demo</span> <span class="t-flag">--profile web-security --name "Web Assessment"</span></div>
    <div class="t-line"><span class="t-success">[+] Engagement demo initialized at ~/.local/share/haibox/engagements/demo/</span></div>
    <div class="t-line"><span class="t-info">[✓] Network bridge created &middot; isolated gateway mode active (internet: denied)</span></div>
    <div class="t-line">&nbsp;</div>
    <div class="t-line"><span class="t-prompt">$</span> <span class="t-cmd">haibox run -- nmap --version</span></div>
    <div class="t-line">Nmap version 7.95 ( https://nmap.org ) &middot; Platform: x86_64-pc-linux-gnu</div>
    <div class="t-line">&nbsp;</div>
    <div class="t-line"><span class="t-prompt">$</span> <span class="t-cmd">haibox shell</span></div>
    <div class="t-line"><span class="t-muted">haibox@runner:/workspace$</span> <span class="t-cmd">ffuf -version</span></div>
    <div class="t-line">ffuf version: 2.3.0 &middot; runner uid: 65534 &middot; rootfs: read-only</div>
    <div class="t-line"><span class="t-muted">haibox@runner:/workspace$</span> <span class="t-cmd">exit</span></div>
    <div class="t-line">&nbsp;</div>
    <div class="t-line"><span class="t-success">[✓] Session ended. Workspace preserved. Audit log entry sealed with SHA-256.</span></div>
  </div>
</div>

---

<div class="section-header" id="features">
  <div class="section-tag">Security Architecture</div>
  <h2 class="section-title">Built for Isolation. Verified by Default.</h2>
  <p class="section-desc">HAIBOX enforces strict trust boundaries between your host, tool runners, and target networks.</p>
</div>

<div class="feature-grid">

  <div class="feature-card">
    <div class="feature-icon-wrapper">
      <span class="twemoji">{% include ".icons/material/shield-lock-outline.svg" %}</span>
    </div>
    <h3>Deny-by-Default Runners</h3>
    <p>Non-root user (UID 65534), read-only root filesystem, dropped capabilities, no privileged mode, and no Docker socket pass-through.</p>
  </div>

  <div class="feature-card">
    <div class="feature-icon-wrapper">
      <span class="twemoji">{% include ".icons/material/folder-lock.svg" %}</span>
    </div>
    <h3>Host-Only Data Boundary</h3>
    <p>Secrets, evidence, reports, and audit logs live exclusively on the host. Only <code>workspace/</code> is mounted writable inside the runner.</p>
  </div>

  <div class="feature-card">
    <div class="feature-icon-wrapper">
      <span class="twemoji">{% include ".icons/material/file-certificate.svg" %}</span>
    </div>
    <h3>Tamper-Evident Audit Trail</h3>
    <p>Every container lifecycle event, shell session, and command execution is logged to a hash-chained SHA-256 host ledger with instant verification.</p>
  </div>

  <div class="feature-card">
    <div class="feature-icon-wrapper">
      <span class="twemoji">{% include ".icons/material/lan.svg" %}</span>
    </div>
    <h3>Isolated Network Default</h3>
    <p>Default engagements run on Docker isolated gateway mode. Zero external connectivity, preventing accidental packet leakage to LAN or internet.</p>
  </div>

</div>

---

<div class="section-header" id="toolkits">
  <div class="section-tag">Curated Toolkits</div>
  <h2 class="section-title">Choose Your Security Toolkit</h2>
  <p class="section-desc">Six reproducible image variants built with pinned manifests, Debian snapshots, and tool verification checks.</p>
</div>

<div class="toolkit-grid">

  <!-- Core -->
  <div class="toolkit-card">
    <div class="toolkit-card-header">
      <div class="toolkit-icon-title">
        <div class="toolkit-icon"><span class="twemoji">{% include ".icons/material/console.svg" %}</span></div>
        <h3>core</h3>
      </div>
      <span class="toolkit-badge badge-active">Active</span>
    </div>
    <div class="toolkit-desc">Base container with minimal triage utilities, shell environment, and diagnostic tools.</div>
    <div class="toolkit-tools-label">Included Tools</div>
    <div class="toolkit-tags">
      <span class="toolkit-tag">bash</span>
      <span class="toolkit-tag">curl</span>
      <span class="toolkit-tag">netcat</span>
      <span class="toolkit-tag">socat</span>
      <span class="toolkit-tag">jq</span>
      <span class="toolkit-tag">file</span>
    </div>
    <div class="toolkit-code">haibox image build core</div>
  </div>

  <!-- Web Security -->
  <div class="toolkit-card">
    <div class="toolkit-card-header">
      <div class="toolkit-icon-title">
        <div class="toolkit-icon"><span class="twemoji">{% include ".icons/material/web.svg" %}</span></div>
        <h3>web-security</h3>
      </div>
      <span class="toolkit-badge badge-active">Active</span>
    </div>
    <div class="toolkit-desc">Complete web penetration testing suite for reconnaissance, scanning, and fuzzing.</div>
    <div class="toolkit-tools-label">Included Tools</div>
    <div class="toolkit-tags">
      <span class="toolkit-tag">nmap</span>
      <span class="toolkit-tag">nuclei</span>
      <span class="toolkit-tag">ffuf</span>
      <span class="toolkit-tag">sqlmap</span>
      <span class="toolkit-tag">dalfox</span>
      <span class="toolkit-tag">nikto</span>
      <span class="toolkit-tag">httpx</span>
    </div>
    <div class="toolkit-code">haibox image build web-security</div>
  </div>

  <!-- Network Security -->
  <div class="toolkit-card">
    <div class="toolkit-card-header">
      <div class="toolkit-icon-title">
        <div class="toolkit-icon"><span class="twemoji">{% include ".icons/material/radar.svg" %}</span></div>
        <h3>network-security</h3>
      </div>
      <span class="toolkit-badge badge-active">Active</span>
    </div>
    <div class="toolkit-desc">Layer 3/4 packet inspection, network discovery, service fingerprinting, and DNS analysis.</div>
    <div class="toolkit-tools-label">Included Tools</div>
    <div class="toolkit-tags">
      <span class="toolkit-tag">tcpdump</span>
      <span class="toolkit-tag">tshark</span>
      <span class="toolkit-tag">nmap</span>
      <span class="toolkit-tag">masscan</span>
      <span class="toolkit-tag">bind9-dnsutils</span>
    </div>
    <div class="toolkit-code">haibox image build network-security</div>
  </div>

  <!-- AD Security -->
  <div class="toolkit-card">
    <div class="toolkit-card-header">
      <div class="toolkit-icon-title">
        <div class="toolkit-icon"><span class="twemoji">{% include ".icons/material/domain.svg" %}</span></div>
        <h3>ad-security</h3>
      </div>
      <span class="toolkit-badge badge-exp">Experimental</span>
    </div>
    <div class="toolkit-desc">Authorized Active Directory assessment, Kerberos authentication triage, and attack-path enumeration.</div>
    <div class="toolkit-tools-label">Included Tools</div>
    <div class="toolkit-tags">
      <span class="toolkit-tag">bloodhound-python</span>
      <span class="toolkit-tag">impacket</span>
      <span class="toolkit-tag">kerbrute</span>
      <span class="toolkit-tag">netexec</span>
    </div>
    <div class="toolkit-code">haibox image build ad-security</div>
  </div>

  <!-- OSINT -->
  <div class="toolkit-card">
    <div class="toolkit-card-header">
      <div class="toolkit-icon-title">
        <div class="toolkit-icon"><span class="twemoji">{% include ".icons/material/eye-outline.svg" %}</span></div>
        <h3>osint</h3>
      </div>
      <span class="toolkit-badge badge-exp">Experimental</span>
    </div>
    <div class="toolkit-desc">Public intelligence gathering, domain reconnaissance, metadata harvesting, and email enumeration.</div>
    <div class="toolkit-tools-label">Included Tools</div>
    <div class="toolkit-tags">
      <span class="toolkit-tag">theHarvester</span>
      <span class="toolkit-tag">sherlock</span>
      <span class="toolkit-tag">sublist3r</span>
      <span class="toolkit-tag">dnsrecon</span>
      <span class="toolkit-tag">photon</span>
    </div>
    <div class="toolkit-code">haibox image build osint</div>
  </div>

  <!-- Full -->
  <div class="toolkit-card">
    <div class="toolkit-card-header">
      <div class="toolkit-icon-title">
        <div class="toolkit-icon"><span class="twemoji">{% include ".icons/material/toolbox-outline.svg" %}</span></div>
        <h3>full</h3>
      </div>
      <span class="toolkit-badge badge-exp">Experimental</span>
    </div>
    <div class="toolkit-desc">Comprehensive toolkit bundling Web, Network, Active Directory, and OSINT capabilities into one image.</div>
    <div class="toolkit-tools-label">Included Tools</div>
    <div class="toolkit-tags">
      <span class="toolkit-tag">all toolkits</span>
      <span class="toolkit-tag">nuclei</span>
      <span class="toolkit-tag">impacket</span>
      <span class="toolkit-tag">tshark</span>
      <span class="toolkit-tag">ffuf</span>
    </div>
    <div class="toolkit-code">haibox image build full</div>
  </div>

</div>

---

<div class="section-header" id="quickstart">
  <div class="section-tag">Quick Start</div>
  <h2 class="section-title">Up and Running in 3 Steps</h2>
  <p class="section-desc">Get your isolated penetration testing environment initialized in minutes.</p>
</div>

<div class="feature-grid">

  <div class="feature-card">
    <div class="feature-icon-wrapper">
      <span class="twemoji">{% include ".icons/material/numeric-1-box-outline.svg" %}</span>
    </div>
    <h3>1. Install HAIBOX</h3>
    <p>Install via the verified release script using <code>uv tool install</code>:</p>
    <div class="toolkit-code" style="margin-top: 0.8rem;">curl -fsSL https://0xssfl.github.io/haibox/install.sh | bash</div>
  </div>

  <div class="feature-card">
    <div class="feature-icon-wrapper">
      <span class="twemoji">{% include ".icons/material/numeric-2-box-outline.svg" %}</span>
    </div>
    <h3>2. Setup Docker Context</h3>
    <p>Create the client-side context and verify host prerequisites:</p>
    <div class="toolkit-code" style="margin-top: 0.8rem;">docker context create haibox --docker "host=unix:///var/run/docker.sock" && haibox init && haibox doctor</div>
  </div>

  <div class="feature-card">
    <div class="feature-icon-wrapper">
      <span class="twemoji">{% include ".icons/material/numeric-3-box-outline.svg" %}</span>
    </div>
    <h3>3. Launch an Engagement</h3>
    <p>Initialize a workspace and open an interactive isolated shell:</p>
    <div class="toolkit-code" style="margin-top: 0.8rem;">haibox engagement init demo --profile web-security --allow-empty-scope && haibox shell</div>
  </div>

</div>

<div class="security-banner">
  <div class="security-banner-icon">
    <span class="twemoji">{% include ".icons/material/alert-octagon.svg" %}</span>
  </div>
  <div class="security-banner-content">
    <h4>Alpha Software Notice & Security Boundaries</h4>
    <p>
      The default runner network has no external connectivity. Scope matchers check policy before execution;
      they are not a replacement for network-layer enforcement. Use HAIBOX only on systems you own or have explicit,
      written authorization to assess. Review <a href="threat-model.md">Threat Model</a> and <a href="https://github.com/0xSSfL/haibox/blob/main/SECURITY.md" target="_blank" rel="noopener">SECURITY.md</a>.
    </p>
  </div>
</div>

<div style="text-align: center; margin: 3rem 0 2rem;">
  <a href="user-guide.md" class="btn-primary" style="font-size: 1.05rem; padding: 0.85rem 2.2rem;">
    <span class="twemoji">{% include ".icons/material/book-open-page-variant.svg" %}</span> Read the Full Documentation
  </a>
</div>
