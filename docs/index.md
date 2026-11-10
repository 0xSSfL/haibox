---
hide:
  - navigation
  - toc
---


<section class="hb-landing" aria-labelledby="hb-hero-title">
  <div class="hb-hero-layout">
    <div class="hb-hero-copy">
      <div class="hb-eyebrow"><span class="hb-status-dot" aria-hidden="true"></span> HAIBOX / 0.1.0 alpha / Docker-native</div>
      <h1 id="hb-hero-title" class="hb-hero-title">Your pentest lab.<span class="hb-highlight">In a box.</span></h1>
      <p class="hb-hero-desc">
        Six curated security toolkits. Separate engagement workspaces.
        A practical, manual-first workstation for authorized security testing,
        with isolated networking by default.
      </p>
      <div class="hb-hero-actions">
        <a class="hb-btn hb-btn-primary" href="user-guide/">Get started <span aria-hidden="true">&#8594;</span></a>
        <a class="hb-btn hb-btn-secondary" href="#toolkits">Explore toolkits</a>
        <a class="hb-btn hb-btn-secondary" href="https://github.com/0xSSfL/haibox" target="_blank" rel="noopener noreferrer">GitHub <span aria-hidden="true">&#8599;</span></a>
      </div>
      <div class="hb-feature-notes" aria-label="Project highlights">
        <span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3 3 7-7"/></svg> Docker on Linux</span>
        <span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3 3 7-7"/></svg> Persistent workspaces</span>
        <span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3 3 7-7"/></svg> 6 toolkits</span>
      </div>
    </div>

    <div class="hb-hero-visual">
      <div class="hb-visual-glow" aria-hidden="true"></div>
      <div class="hb-cube-stage" aria-hidden="true">
        <div class="hb-cube-orbit"></div>
        <div class="hb-cube">
          <div class="hb-cube-face hb-cube-front"><img src="assets/haibox-mark.png" alt="" loading="lazy"></div>
          <div class="hb-cube-face hb-cube-back"></div>
          <div class="hb-cube-face hb-cube-right"></div>
          <div class="hb-cube-face hb-cube-left"></div>
          <div class="hb-cube-face hb-cube-top"></div>
          <div class="hb-cube-face hb-cube-bottom"></div>
        </div>
      </div>
      <div class="hb-terminal" role="img" aria-label="Illustrative terminal preview showing the HAIBOX doctor, image build, engagement creation, and shell workflow. These are examples, not live results.">
        <div class="hb-terminal-head">
          <span class="hb-terminal-dots" aria-hidden="true"><i></i><i></i><i></i></span>
          <span class="hb-terminal-caption">haibox / local workstation</span>
          <span class="hb-terminal-preview">DEMO</span>
        </div>
        <div class="hb-terminal-body" aria-hidden="true">
          <div class="hb-terminal-line"><span class="hb-comment"># Illustrative workflow (not live output)</span></div>
          <div class="hb-terminal-line"><span class="hb-prompt">$</span>haibox doctor</div>
          <div class="hb-terminal-line"><span class="hb-output">&gt; review Docker context and host requirements</span></div>
          <div class="hb-terminal-line"><span class="hb-prompt">$</span>haibox image build <span class="hb-cyan">web-security</span></div>
          <div class="hb-terminal-line"><span class="hb-output">&gt; builds a pinned toolkit image locally</span></div>
          <div class="hb-terminal-line"><span class="hb-prompt">$</span>haibox engagement init demo <span class="hb-cyan">--profile web-security --allow-empty-scope</span></div>
          <div class="hb-terminal-line"><span class="hb-output">&gt; create an offline lab workspace</span></div>
          <div class="hb-terminal-line"><span class="hb-prompt">$</span>haibox shell <span class="hb-terminal-caret" aria-hidden="true"></span></div>
        </div>
        <div class="hb-terminal-foot">Offline by default &middot; illustrative demo &middot; no commands executed</div>
      </div>
      <div class="hb-visual-controls"><button class="hb-motion-toggle" type="button" aria-pressed="false" hidden>Pause animation</button></div>
    </div>
  </div>
  <div class="hb-landing-alpha"><span aria-hidden="true">&#9888;</span><span><strong>Alpha release.</strong> External target routing and VPN/AI integration are unfinished, and image dependency scans still contain HIGH/CRITICAL findings. <a href="verification-status/">View verification status</a>.</span></div>
</section>

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
