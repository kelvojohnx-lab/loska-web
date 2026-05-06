/* ── LOSKA COMMUNICATIONS – MAIN JS ── */
document.addEventListener('DOMContentLoaded', () => {

  // ── Navbar scroll effect ──
  const navbar = document.getElementById('navbar');
  window.addEventListener('scroll', () => {
    navbar?.classList.toggle('scrolled', window.scrollY > 30);
  }, { passive: true });

  // ── Hamburger / mobile nav ──
  const hamburger = document.getElementById('hamburger');
  const navLinks  = document.getElementById('navLinks');
  if (hamburger && navLinks) {
    hamburger.addEventListener('click', () => {
      hamburger.classList.toggle('open');
      navLinks.classList.toggle('open');
    });
    document.addEventListener('click', (e) => {
      if (!hamburger.contains(e.target) && !navLinks.contains(e.target)) {
        hamburger.classList.remove('open');
        navLinks.classList.remove('open');
      }
    });
  }

  // ── Flash auto-dismiss ──
  document.querySelectorAll('.flash').forEach(el => {
    setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateX(20px)'; }, 4500);
    setTimeout(() => el.remove(), 5000);
  });

  // ── Cart badge live update ──
  async function updateCartBadge() {
    try {
      const r = await fetch('/api/cart-count');
      const d = await r.json();
      const badge = document.getElementById('cartBadge');
      if (badge) badge.textContent = d.count || 0;
    } catch {}
  }
  updateCartBadge();

  // ── Quantity controls ──
  document.querySelectorAll('.qty-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const input = btn.closest('.qty-control')?.querySelector('.qty-input');
      if (!input) return;
      let val = parseInt(input.value) || 1;
      if (btn.dataset.action === 'inc') val++;
      else if (btn.dataset.action === 'dec' && val > 1) val--;
      input.value = val;
    });
  });

  // ── Amount preset buttons (airtime) ──
  document.querySelectorAll('.amount-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.amount-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const amountInput = document.getElementById('amount');
      if (amountInput) amountInput.value = btn.dataset.value;
    });
  });

  // ── Product / accessory search & filter ──
  const searchInput    = document.getElementById('searchInput');
  const categoryFilter = document.getElementById('categoryFilter');
  const productCards   = document.querySelectorAll('.product-card[data-brand]');

  function filterProducts() {
    const q   = (searchInput?.value || '').toLowerCase();
    const cat = (categoryFilter?.value || '').toLowerCase();
    productCards.forEach(card => {
      const brand = (card.dataset.brand || '').toLowerCase();
      const model = (card.dataset.model || '').toLowerCase();
      const matchQ   = !q   || brand.includes(q) || model.includes(q);
      const matchCat = !cat || brand === cat || model.includes(cat);
      card.style.display = matchQ && matchCat ? '' : 'none';
    });
  }
  searchInput?.addEventListener('input', filterProducts);
  categoryFilter?.addEventListener('change', filterProducts);

  // ── Payment method toggle ──
  document.querySelectorAll('input[name="payment_method"]').forEach(radio => {
    radio.addEventListener('change', () => {
      document.querySelectorAll('.payment-section').forEach(s => s.classList.add('hidden'));
      const section = document.getElementById(`pay-${radio.value}`);
      if (section) section.classList.remove('hidden');
    });
  });

  // ── Admin confirm delete ──
  document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', (e) => {
      if (!confirm(el.dataset.confirm || 'Are you sure?')) e.preventDefault();
    });
  });

  // ── FAQ accordion ──
  window.toggleFaq = function(btn) {
    const answer = btn.nextElementSibling;
    const isOpen = btn.classList.contains('open');
    document.querySelectorAll('.faq-question.open').forEach(b => {
      b.classList.remove('open');
      b.nextElementSibling.classList.remove('open');
    });
    if (!isOpen) {
      btn.classList.add('open');
      answer.classList.add('open');
    }
  };

  // ── Animate on scroll ──
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) e.target.classList.add('visible');
    });
  }, { threshold: 0.1 });
  document.querySelectorAll('.animate-up').forEach(el => observer.observe(el));

  // ── Product image fallback ──
  document.querySelectorAll('.product-img img').forEach(img => {
    img.addEventListener('error', () => {
      img.style.display = 'none';
      const ph = img.nextElementSibling;
      if (ph) ph.style.display = 'flex';
    });
  });

  // ── Form validation ──
  document.querySelectorAll('form[data-validate]').forEach(form => {
    form.addEventListener('submit', (e) => {
      let valid = true;
      form.querySelectorAll('[required]').forEach(field => {
        if (!field.value.trim()) {
          field.classList.add('error');
          valid = false;
        } else {
          field.classList.remove('error');
        }
      });
      const emailField = form.querySelector('[type="email"]');
      if (emailField && emailField.value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailField.value)) {
        emailField.classList.add('error');
        valid = false;
      }
      if (!valid) {
        e.preventDefault();
        const first = form.querySelector('.error');
        first?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        first?.focus();
      }
    });
  });
});
