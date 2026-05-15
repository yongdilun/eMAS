document.addEventListener('DOMContentLoaded', () => {
    const contentBody = document.getElementById('content-body');
    const bcCurrent = document.getElementById('bc-current');
    const navLinks = document.querySelectorAll('.nav-link');
    const themeToggle = document.getElementById('theme-toggle');

    // Initialize Highlight.js
    hljs.configure({ ignoreUnescapedHTML: true });

    // Navigation Handler
    const navigate = async () => {
        const fullHash = window.location.hash.substring(1) || 'welcome';
        // Handle deep links (e.g., #chapter/section)
        const [hash, sectionId] = fullHash.split('/');
        
        const activeLink = document.querySelector(`[data-chapter="${hash}"]`) || 
                          document.querySelector(`a[href="#${hash}"]`) ||
                          document.querySelector('[data-chapter="welcome"]');
        
        // Update UI
        navLinks.forEach(link => link.classList.remove('active'));
        if (activeLink) {
            activeLink.classList.add('active');
            bcCurrent.textContent = activeLink.textContent;
        }

        // Welcome / Home redirect
        if (hash === 'welcome' || hash === 'home' || hash === 'overview') {
            renderWelcome();
            return;
        }

        try {
            contentBody.innerHTML = '<div class="loader">Loading...</div>';
            
            // Try loading .html first, then .md
            let response = await fetch(`chapters/${hash}.html`);
            let isHtml = response.ok;
            
            if (!isHtml) {
                response = await fetch(`chapters/${hash}.md`);
                if (!response.ok) throw new Error('Chapter not found');
            }
            
            const content = await response.text();
            contentBody.className = `content-body ${isHtml ? 'html-body' : 'markdown-body'} fade-in`;
            
            if (isHtml) {
                contentBody.innerHTML = content;
                // Initialize Mermaid if present
                if (window.mermaid) {
                    mermaid.init(undefined, '.mermaid');
                }
            } else {
                contentBody.innerHTML = marked.parse(content);
            }
            
            // Generate TOC and handle section scrolling
            generateTOC(hash);

            // Re-highlight code blocks
            contentBody.querySelectorAll('pre code').forEach((block) => {
                hljs.highlightElement(block);
            });

            // Scroll to section or top
            if (sectionId) {
                const element = document.getElementById(sectionId);
                if (element) {
                    element.scrollIntoView({ behavior: 'smooth' });
                }
            } else {
                document.querySelector('.content-area').scrollTop = 0;
            }
        } catch (err) {
            contentBody.innerHTML = `
                <div class="error-state">
                    <h1>404</h1>
                    <p>The documentation chapter "${hash}" could not be found or is still being written.</p>
                    <a href="#welcome" class="nav-link">Return Home</a>
                </div>
            `;
        }
    };

    const generateTOC = (chapterHash) => {
        const tocContainer = document.getElementById('toc-content');
        if (!tocContainer) return;
        
        tocContainer.innerHTML = '';
        const headings = contentBody.querySelectorAll('h2, h3');
        
        if (headings.length === 0) {
            tocContainer.closest('.chapter-toc').style.display = 'none';
            return;
        }

        tocContainer.closest('.chapter-toc').style.display = 'block';
        const ul = document.createElement('ul');
        
        headings.forEach((h, index) => {
            const id = h.id || h.textContent.toLowerCase().replace(/\s+/g, '-');
            h.id = id;
            
            const li = document.createElement('li');
            const a = document.createElement('a');
            a.href = `#${chapterHash}/${id}`;
            a.textContent = h.textContent;
            if (h.tagName === 'H3') li.style.paddingLeft = '1rem';
            
            li.appendChild(a);
            ul.appendChild(li);
        });
        
        tocContainer.appendChild(ul);
    };

    const renderWelcome = () => {
        contentBody.className = 'content-body fade-in';
        contentBody.innerHTML = `
            <div class="hero-section">
                <h1>The Factory Agent Wiki</h1>
                <p class="lead">Industrial-grade orchestration for autonomous manufacturing operations.</p>
                <div class="feature-grid">
                    <div class="feature-card">
                        <div class="feature-icon">🛡️</div>
                        <h3>Deterministic Safety</h3>
                        <p>Stateful graph execution with rigid two-phase commit protocols and real-time guardrails.</p>
                    </div>
                    <div class="feature-card">
                        <div class="feature-icon">🧠</div>
                        <h3>Complex Reasoning</h3>
                        <p>Multi-intent decomposition and hierarchical planning logic for high-stakes environments.</p>
                    </div>
                    <div class="feature-card">
                        <div class="feature-icon">👁️</div>
                        <h3>Observability</h3>
                        <p>Transparent agent reasoning via SSE event streaming and full LangSmith telemetry.</p>
                    </div>
                </div>
            </div>
        `;
        // Hide TOC on welcome page
        const toc = document.querySelector('.chapter-toc');
        if (toc) toc.style.display = 'none';
    };

    // Theme Toggle
    themeToggle.addEventListener('click', () => {
        document.body.classList.toggle('dark-theme');
        const isDark = document.body.classList.contains('dark-theme');
        localStorage.setItem('wiki-theme', isDark ? 'dark' : 'light');
    });

    // Initialize Theme
    const savedTheme = localStorage.getItem('wiki-theme');
    if (savedTheme === 'dark' || (!savedTheme && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.body.classList.add('dark-theme');
    }

    // Listen for hash changes
    window.addEventListener('hashchange', navigate);
    
    // Initial load
    navigate();
});
