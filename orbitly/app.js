const root = document.documentElement;
const themeToggle = document.querySelector('[data-theme-toggle]');
const themeLabel = document.querySelector('[data-theme-label]');
const themeMeta = document.querySelector('meta[name="theme-color"]');

const storedTheme = localStorage.getItem('orbitly-theme');
if (storedTheme === 'light' || storedTheme === 'dark') root.dataset.theme = storedTheme;

function syncThemeUI() {
  const isLight = root.dataset.theme === 'light';
  if (themeLabel) themeLabel.textContent = isLight ? 'Dark mode' : 'Light mode';
  if (themeToggle) themeToggle.setAttribute('aria-label', isLight ? 'Switch to dark theme' : 'Switch to light theme');
  if (themeMeta) themeMeta.setAttribute('content', isLight ? '#f3f1e9' : '#07101a');
}

themeToggle?.addEventListener('click', () => {
  root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
  localStorage.setItem('orbitly-theme', root.dataset.theme);
  syncThemeUI();
});
syncThemeUI();

const matchData = {
  'Creative technology|Big city energy': ['Parsons School of Design', 'Because your creative edge wants a city that keeps moving.'],
  'Creative technology|Coastal calm': ['Aalto University', 'Because your imagination grows when design meets open space.'],
  'Creative technology|Mountain air': ['University of British Columbia', 'Because you want your ideas surrounded by a bigger horizon.'],
  'Climate science|Big city energy': ['Imperial College London', 'Because your climate ambition belongs where ideas become action.'],
  'Climate science|Coastal calm': ['University of Auckland', 'Because your curiosity needs the ocean — and a lab with momentum.'],
  'Climate science|Mountain air': ['ETH Zürich', 'Because your systems-thinking belongs close to the source.'],
  'Business & design|Big city energy': ['IE University', 'Because your best work happens where strategy meets culture.'],
  'Business & design|Coastal calm': ['Monash University', 'Because you are building a career with room to breathe.'],
  'Business & design|Mountain air': ['University of Innsbruck', 'Because your ambition has both altitude and perspective.']
};

const selections = { study: 'Creative technology', place: 'Big city energy' };
const resultTitle = document.querySelector('[data-result-title]');
const resultCopy = document.querySelector('[data-result-copy]');
const resultStudy = document.querySelector('[data-result-study]');
const resultPlace = document.querySelector('[data-result-place]');

function updateMatch() {
  if (!resultTitle) return;
  const key = `${selections.study}|${selections.place}`;
  const [title, copy] = matchData[key];
  resultTitle.animate([{ opacity: .25, transform: 'translateY(5px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 420, easing: 'cubic-bezier(.22,.8,.22,1)' });
  resultTitle.textContent = title;
  resultCopy.textContent = copy;
  resultStudy.textContent = selections.study;
  resultPlace.textContent = selections.place;
}

document.querySelectorAll('[data-choice-group]').forEach(group => {
  group.addEventListener('click', event => {
    const chip = event.target.closest('.choice-chip');
    if (!chip) return;
    group.querySelectorAll('.choice-chip').forEach(item => item.classList.remove('is-selected'));
    chip.classList.add('is-selected');
    selections[group.dataset.choiceGroup] = chip.dataset.value;
    updateMatch();
  });
});

document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', () => {
    document.querySelectorAll('.nav-link').forEach(item => item.classList.remove('is-active'));
    link.classList.add('is-active');
  });
});

document.querySelector('[data-menu-button]')?.addEventListener('click', () => {
  const nav = document.querySelector('.nav-links');
  const isOpen = nav.classList.toggle('is-mobile-open');
  nav.style.display = isOpen ? 'flex' : '';
});

document.querySelectorAll('.suggestion-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    const input = document.querySelector('[data-chat-form] input');
    if (input) { input.value = chip.dataset.suggestion; input.focus(); }
  });
});

document.querySelector('[data-chat-form]')?.addEventListener('submit', event => {
  event.preventDefault();
  const input = event.currentTarget.querySelector('input');
  if (!input.value.trim()) return;
  input.value = '';
  input.placeholder = 'Signal received. Vera will respond here...';
});

document.querySelectorAll('[data-auth-form]').forEach(form => {
  form.addEventListener('submit', event => {
    event.preventDefault();
    const status = form.querySelector('[data-form-status]');
    if (status) status.textContent = form.closest('.auth-form-wrap').querySelector('h2').textContent.includes('Start') ? 'Your orbit is ready to begin.' : 'Welcome back. Opening your workspace...';
  });
});
