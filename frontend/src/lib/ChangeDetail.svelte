<script>
  export let change = null;
  export let onBack = () => {};

  function formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function getScoreClass(score) {
    if (score >= 8) return 'high';
    if (score >= 5) return 'medium';
    if (score >= 3) return 'low';
    return 'info';
  }

  function formatDiff(diffText) {
    if (!diffText) return '';
    return diffText.split('\n').map(line => {
      if (line.startsWith('+')) return `<span class="add">${escapeHtml(line)}</span>`;
      if (line.startsWith('-')) return `<span class="del">${escapeHtml(line)}</span>`;
      return `<span class="ctx">${escapeHtml(line)}</span>`;
    }).join('\n');
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function truncatedDiff(diffText, maxLines = 100) {
    if (!diffText) return '';
    const lines = diffText.split('\n');
    if (lines.length <= maxLines) return diffText;
    return lines.slice(0, maxLines).join('\n') + '\n\n[... diff truncated ...]';
  }
</script>

{#if !change}
  <div class="empty">No change selected.</div>
{:else}
  <div class="detail-view">
    <button class="back-btn" on:click={onBack}>← Back to list</button>

    <header class="detail-header">
      <div class="title-section">
        <div class="commit-hash">
          <a href="https://github.com/MicrosoftDocs/azure-docs/commit/{change.commit_hash}" 
             target="_blank"
             rel="noopener">
            {change.commit_hash?.slice(0, 12)}
          </a>
        </div>
        <h2>{change.commit_message?.split('\n')[0] || 'Untitled Change'}</h2>
      </div>

      <div class="score-badge {getScoreClass(change.score || 0)}">
        <div class="score-value">{change.score || 0}</div>
        <div class="score-label">Security Score</div>
      </div>
    </header>

    <div class="detail-meta">
      <div class="meta-row">
        <span class="label">Repository:</span>
        <span class="value">{change.repo_name}</span>
      </div>

      <div class="meta-row">
        <span class="label">Author:</span>
        <span class="value">{change.author}</span>
      </div>

      <div class="meta-row">
        <span class="label">Date:</span>
        <span class="value">{formatDate(change.commit_date)}</span>
      </div>

      <div class="meta-row">
        <span class="label">Risk Level:</span>
        <span class="value risk-{change.risk_level}">{change.risk_level}</span>
      </div>
    </div>

    {#if change.summary}
      <section class="summary">
        <h3>📝 Summary</h3>
        <p>{change.summary}</p>
      </section>
    {/if}

    {#if change.tags?.length > 0}
      <section class="tags-section">
        <h3>🏷️ Tags</h3>
        <div class="tags-list">
          {#each change.tags as tag}
            <span class="tag">{tag}</span>
          {/each}
        </div>
      </section>
    {/if}

    {#if change.files_changed?.length > 0}
      <section class="files-section">
        <h3>📁 Files Changed</h3>
        <ul class="file-list">
          {#each change.files_changed as file}
            <li>{file}</li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if change.diff_summary}
      <section class="diff-section">
        <h3>📊 Diff Summary</h3>
        <pre class="diff-text">{truncatedDiff(change.diff_summary, 150)}</pre>
      </section>
    {/if}

  </div>
{/if}

<style>
  .empty {
    text-align: center;
    padding: 4rem;
    color: #8b949e;
  }

  .detail-view {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 1.5rem;
  }

  .back-btn {
    background: #21262d;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 0.5rem 1rem;
    border-radius: 6px;
    cursor: pointer;
    margin-bottom: 1rem;
  }

  .back-btn:hover {
    border-color: #58a6ff;
  }

  .detail-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid #30363d;
  }

  .commit-hash a {
    font-family: ui-monospace, monospace;
    color: #58a6ff;
    text-decoration: none;
    font-size: 0.9rem;
  }

  .commit-hash a:hover {
    text-decoration: underline;
  }

  .title-section h2 {
    margin: 0.5rem 0 0 0;
    font-size: 1.3rem;
    line-height: 1.4;
  }

  .score-badge {
    text-align: center;
    padding: 0.75rem 1.25rem;
    border-radius: 8px;
    min-width: 80px;
  }

  .score-badge.high {
    background: #da363333;
    color: #f85149;
  }

  .score-badge.medium {
    background: #d2992233;
    color: #d29922;
  }

  .score-badge.low {
    background: #2ea04333;
    color: #3fb950;
  }

  .score-badge.info {
    background: #8b949e33;
    color: #8b949e;
  }

  .score-value {
    font-size: 2rem;
    font-weight: bold;
  }

  .score-label {
    font-size: 0.75rem;
    opacity: 0.8;
  }

  .detail-meta {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.75rem;
    margin-bottom: 1.5rem;
    padding: 1rem;
    background: #0d1117;
    border-radius: 6px;
  }

  .meta-row {
    display: flex;
    gap: 0.5rem;
  }

  .label {
    color: #8b949e;
  }

  .value {
    color: #c9d1d9;
  }

  .value.risk-high {
    color: #f85149;
    font-weight: bold;
  }

  .value.risk-medium {
    color: #d29922;
    font-weight: bold;
  }

  .value.risk-low {
    color: #3fb950;
  }

  section {
    margin-top: 1.5rem;
  }

  section h3 {
    margin: 0 0 0.75rem 0;
    font-size: 1rem;
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .summary p {
    line-height: 1.6;
    margin: 0;
  }

  .tags-list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .tag {
    background: #388bfd33;
    color: #58a6ff;
    padding: 0.3rem 0.75rem;
    border-radius: 12px;
    font-size: 0.85rem;
  }

  .file-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .file-list li {
    padding: 0.4rem 0;
    border-bottom: 1px solid #21262d;
    font-family: ui-monospace, monospace;
    font-size: 0.9rem;
    color: #a371f7;
  }

  .file-list li:last-child {
    border-bottom: none;
  }

  .diff-section pre {
    background: #0d1117;
    padding: 1rem;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 0.85rem;
    line-height: 1.5;
    max-height: 500px;
    overflow-y: auto;
  }

  .rationale p {
    background: #1f6feb15;
    border-left: 3px solid #58a6ff;
    padding: 1rem;
    margin: 0;
    font-style: italic;
  }
</style>
