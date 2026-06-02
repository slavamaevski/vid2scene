(function () {
  const scope = document.getElementById('docs');
  if (!scope) return;

  // Enhance code blocks: wrap and add copy buttons
  const preBlocks = scope.querySelectorAll('div.bg-dark pre, div.bg-light pre, pre');
  preBlocks.forEach((pre) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'code-block ' + (pre.closest('.bg-dark') ? 'dark' : pre.closest('.bg-light') ? 'light' : 'light');
    const parent = pre.parentElement;
    if (!parent) return;
    parent.replaceWith(wrapper);
    wrapper.appendChild(pre);

    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.innerHTML = '<i class="bi bi-clipboard"></i> Copy';
    btn.addEventListener('click', async () => {
      try {
        const text = pre.innerText;
        await navigator.clipboard.writeText(text);
        btn.innerHTML = '<i class="bi bi-check2"></i> Copied';
        setTimeout(() => (btn.innerHTML = '<i class="bi bi-clipboard"></i> Copy'), 1500);
      } catch (e) {
        btn.innerHTML = '<i class="bi bi-clipboard"></i> Copy';
      }
    });
    wrapper.appendChild(btn);
  });

  // Heading anchors for h2/h3
  const headings = scope.querySelectorAll('h2, h3');
  const slugify = (text) =>
    text
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-');

  headings.forEach((h) => {
    if (!h.id) h.id = slugify(h.textContent || '');
    const a = document.createElement('a');
    a.href = `#${h.id}`;
    a.className = 'anchor-link';
    a.innerHTML = '<i class="bi bi-link-45deg"></i>';
    h.appendChild(a);
  });

  // Back to top button
  const backToTop = document.createElement('button');
  backToTop.id = 'docs-back-to-top';
  backToTop.className = 'btn btn-primary btn-sm';
  backToTop.innerHTML = '<i class="bi bi-arrow-up"></i>';
  document.body.appendChild(backToTop);

  const toggleBackToTop = () => {
    if (window.scrollY > 400) backToTop.classList.add('show');
    else backToTop.classList.remove('show');
  };
  toggleBackToTop();
  window.addEventListener('scroll', toggleBackToTop);
  backToTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
})();



