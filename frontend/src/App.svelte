<script>
  import { onMount } from 'svelte';
  import ChangesList from './lib/ChangesList.svelte';
  import ChangeDetail from './lib/ChangeDetail.svelte';
  import Stats from './lib/Stats.svelte';

  const API_URL = '';

  let changes = $state([]);
  let stats = $state(null);
  let loading = $state(false);
  let error = $state(null);
  let selectedChange = $state(null);
  let view = $state('list');

  let minScore = $state(0);
  let riskLevel = $state('');
  let searchQuery = $state('');

  async function fetchChanges() {
    loading = true;
    error = null;
    try {
      const params = new URLSearchParams();
      if (minScore > 0) params.append('min_score', minScore);
      if (riskLevel) params.append('risk_level', riskLevel);
      if (searchQuery) params.append('search', searchQuery);

      const url = `${API_URL}/changes?${params}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      changes = data.changes || [];
    } catch (err) {
      error = err.message;
    } finally {
      loading = false;
    }
  }

  async function fetchStats() {
    try {
      const res = await fetch(`${API_URL}/stats`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      stats = await res.json();
    } catch (err) {
      console.error('Stats error:', err);
    }
  }

  function selectChange(change) {
    selectedChange = change;
    view = 'detail';
  }

  function goBack() {
    selectedChange = null;
    view = 'list';
  }

  onMount(() => {
    fetchChanges();
    fetchStats();
  });

  function showStats() {
    view = 'stats';
  }

  function showList() {
    view = 'list';
  }
</script>

<main class="footnote-app">
  <header class="header">
    <div class="brand">
      <h1>📖 Footnote</h1>
      <span class="tagline">The real story is in the footnotes</span>
    </div>
    <nav class="nav">
      <button class:active={view === 'list'} onclick={showList}>Changes</button>
      <button class:active={view === 'stats'} onclick={showStats}>Stats</button>
    </nav>
  </header>

  {#if view === 'list'}
    <div class="filters">
      <div class="filter-group">
        <label>Min Score:</label>
        <input type="range" min="0" max="10" step="1" bind:value={minScore} onchange={fetchChanges} />
        <span class="score-badge">{minScore}</span>
      </div>

      <div class="filter-group">
        <label>Risk:</label>
        <select bind:value={riskLevel} onchange={fetchChanges}>
          <option value="">All</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
          <option value="informational">Info</option>
        </select>
      </div>

      <div class="filter-group search">
        <input type="text" placeholder="Search commits..." bind:value={searchQuery} oninput={fetchChanges} />
      </div>
    </div>

    {#if loading}
      <div class="loading">Loading changes...</div>
    {:else if error}
      <div class="error">Error: {error}</div>
    {:else}
      <ChangesList {changes} onSelect={selectChange} />
    {/if}

  {:else if view === 'detail'}
    <ChangeDetail change={selectedChange} onBack={goBack} />

  {:else if view === 'stats'}
    <Stats {stats} onBack={showList} />
  {/if}

  <footer class="footer">
    <p>API: {API_URL || '(same domain)'}</p>
  </footer>
</main>

<style>
  :global(body) {
    margin: 0;
    font-family: system-ui, -apple-system, sans-serif;
    background: #0d1117;
    color: #c9d1d9;
  }

  .footnote-app {
    max-width: 1200px;
    margin: 0 auto;
    padding: 1rem;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid #30363d;
    margin-bottom: 1.5rem;
  }

  .brand h1 {
    margin: 0;
    font-size: 1.8rem;
    color: #58a6ff;
  }

  .tagline {
    color: #8b949e;
    font-size: 0.9rem;
    margin-left: 0.5rem;
  }

  .nav button {
    background: #21262d;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 0.5rem 1rem;
    margin-left: 0.5rem;
    border-radius: 6px;
    cursor: pointer;
  }

  .nav button.active,
  .nav button:hover {
    background: #30363d;
    border-color: #58a6ff;
  }

  .filters {
    display: flex;
    gap: 1rem;
    align-items: center;
    margin-bottom: 1.5rem;
    flex-wrap: wrap;
  }

  .filter-group {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .filter-group label {
    color: #8b949e;
    font-size: 0.9rem;
  }

  .filter-group input[type="range"] {
    width: 100px;
  }

  .filter-group select,
  .filter-group input[type="text"] {
    background: #21262d;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 0.4rem 0.8rem;
    border-radius: 4px;
  }

  .filter-group.search input {
    width: 250px;
  }

  .score-badge {
    background: #238636;
    color: white;
    padding: 0.2rem 0.5rem;
    border-radius: 4px;
    font-weight: bold;
    min-width: 1.5rem;
    text-align: center;
  }

  .loading,
  .error {
    text-align: center;
    padding: 3rem;
    color: #8b949e;
  }

  .error {
    color: #f85149;
  }

  .footer {
    margin-top: auto;
    padding-top: 2rem;
    text-align: center;
    color: #484f58;
    font-size: 0.8rem;
  }
</style>
