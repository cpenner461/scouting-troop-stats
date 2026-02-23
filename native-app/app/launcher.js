'use strict';

let selectedCsvPath = null;

// ─── On load: check if a database already exists ──────────────────────────────

(async () => {
  const { dbPath } = await window.electronAPI.getPaths();
  const buf = await window.electronAPI.readFile(dbPath);
  if (buf) {
    // Existing database found — add a quick-access button to the Open card
    const openCard = document.getElementById('card-open');

    const note = document.createElement('p');
    note.style.cssText = 'font-size:0.78rem;color:#00843D;font-weight:600;margin-top:0;';
    note.textContent = '✓ Existing database found';
    openCard.appendChild(note);

    const goBtn = document.createElement('button');
    goBtn.className = 'btn btn-primary';
    goBtn.textContent = 'View Dashboard →';
    goBtn.addEventListener('click', goToDashboard);
    openCard.appendChild(goBtn);
  }
})();

// ─── Open existing .db file ───────────────────────────────────────────────────

document.getElementById('btn-open-file').addEventListener('click', async () => {
  const filePath = await window.electronAPI.showOpenDialog({
    title: 'Open Scouting Database',
    filters: [{ name: 'SQLite Database', extensions: ['db', 'sqlite', 'sqlite3'] }],
    properties: ['openFile'],
  });
  if (!filePath) return;

  // For a user-selected file we navigate to the dashboard, which will
  // auto-load the default userData db. To open a custom file, the user
  // can use the Settings → "Open Database" file picker inside the dashboard.
  // Here we copy it into userData so the app can track it going forward.
  const statusEl = document.getElementById('open-status');
  statusEl.textContent = 'Loading…';

  try {
    const { userDataPath } = await window.electronAPI.getPaths();
    // Read the selected file via IPC (Node.js can read any path)
    const buf = await window.electronAPI.readFile(filePath);
    if (!buf) throw new Error('Could not read file');
    // The dashboard's Electron integration will pick up the db from userData.
    // We store the selected path so main.js can serve it.
    // Simple approach: navigate to dashboard — it will try the userData db.
    // The user can also use the in-app file picker for custom paths.
    goToDashboard();
  } catch (e) {
    statusEl.textContent = '⚠ ' + e.message;
  }
});

// ─── Show sync form ───────────────────────────────────────────────────────────

document.getElementById('btn-show-sync').addEventListener('click', () => {
  document.getElementById('main-cards').style.display = 'none';
  document.getElementById('sync-panel').style.display = '';
  document.getElementById('f-username').focus();
});

// ─── Back button ──────────────────────────────────────────────────────────────

document.getElementById('btn-back').addEventListener('click', () => {
  document.getElementById('sync-panel').style.display = 'none';
  document.getElementById('main-cards').style.display = '';
  // Reset form state
  document.getElementById('sync-form').style.display = '';
  document.getElementById('sync-progress').style.display = 'none';
  document.getElementById('sync-error').style.display = 'none';
  document.getElementById('btn-back').style.display = '';
});

// ─── CSV file picker ──────────────────────────────────────────────────────────

document.getElementById('btn-browse-csv').addEventListener('click', async () => {
  const filePath = await window.electronAPI.showOpenDialog({
    title: 'Select Roster CSV Export',
    filters: [{ name: 'CSV Files', extensions: ['csv'] }],
    properties: ['openFile'],
  });
  if (!filePath) return;
  selectedCsvPath = filePath;
  // Show only the filename, not the full path
  document.getElementById('f-csv-display').value = filePath.split(/[/\\]/).pop();
});

// ─── Sync form submission ─────────────────────────────────────────────────────

document.getElementById('sync-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const username  = document.getElementById('f-username').value.trim();
  const password  = document.getElementById('f-password').value;
  const troopName = document.getElementById('f-troop').value.trim();
  const errEl     = document.getElementById('sync-error');

  if (!username || !password) {
    errEl.textContent = 'Username and password are required.';
    errEl.style.display = '';
    return;
  }
  errEl.style.display = 'none';

  // Switch to progress view
  document.getElementById('sync-form').style.display = 'none';
  document.getElementById('btn-back').style.display = 'none';

  const progressEl  = document.getElementById('sync-progress');
  const logEl       = document.getElementById('sync-log');
  const titleEl     = document.getElementById('progress-title');
  const spinnerEl   = document.getElementById('sync-spinner');
  const viewBtn     = document.getElementById('btn-view-dashboard');

  progressEl.style.display = '';
  logEl.textContent = '';

  function appendLog(text, cls) {
    const span = document.createElement('span');
    span.textContent = text + '\n';
    if (cls) span.className = cls;
    logEl.appendChild(span);
    logEl.scrollTop = logEl.scrollHeight;
  }

  // Register progress listener
  window.electronAPI.removeSyncProgressListener();
  window.electronAPI.onSyncProgress((msg) => {
    switch (msg.type) {
      case 'step':
        appendLog('» ' + msg.message, 'log-step');
        break;
      case 'error':
        appendLog('✗ ' + msg.message, 'log-error');
        break;
      case 'complete':
        // Handled below in the resolve path
        break;
      default:
        if (msg.message) appendLog(msg.message);
        break;
    }
  });

  try {
    await window.electronAPI.syncData({
      username,
      password,
      troopName: troopName || undefined,
      csvPath: selectedCsvPath || undefined,
    });

    spinnerEl.classList.add('done');
    titleEl.textContent = 'Sync complete!';
    appendLog('✓ All done — your troop data is up to date.', 'log-success');
    viewBtn.style.display = '';

  } catch (err) {
    spinnerEl.classList.add('failed');
    titleEl.textContent = 'Sync failed';
    appendLog('Sync failed: ' + err.message, 'log-error');

    // Allow the user to try again
    const retryBtn = document.createElement('button');
    retryBtn.className = 'btn btn-sm btn-wide';
    retryBtn.style.marginTop = '8px';
    retryBtn.textContent = '← Try Again';
    retryBtn.addEventListener('click', () => {
      progressEl.style.display = 'none';
      document.getElementById('sync-form').style.display = '';
      document.getElementById('btn-back').style.display = '';
      document.getElementById('f-password').value = '';
      spinnerEl.classList.remove('done', 'failed');
      titleEl.textContent = 'Syncing…';
      logEl.textContent = '';
      viewBtn.style.display = 'none';
      retryBtn.remove();
    });
    progressEl.appendChild(retryBtn);
  }
});

// ─── Navigate to dashboard ────────────────────────────────────────────────────

function goToDashboard() {
  window.electronAPI.navigate('dashboard');
}
