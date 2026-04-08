<script>
  export let changes = [];
  export let onSelect = (change) => {};

  function formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function formatHash(hash) {
    return hash?.slice(0, 8) || '';
  }

  function getScoreClass(score) {
    if (score >= 8) return 'high';
    if (score >= 5) return 'medium';
    if (score >= 3) return 'low';
    return 'info';
  }

  function getRiskIcon(level) {
    const icons = {
      high: '🔴',
      medium: '🟡',
      low: '🟢',
      informational: '⚪'
    };
    return icons[level] || '⚪';
  }
</script>

{#if changes.length === 0}
  <div class="empty">No changes found matching your criteria.</div>
{:else}
  <div class="changes-list">
    {#each changes as change}
      <div class="change-card" on:click={() => onSelect(change)}>
        <div class="card-header">
          <div class="score-section">
            <span class="score {getScoreClass(change.llm_score || 0)}">
              {change.llm_score || 0}
            </span>
            <span class="risk">{getRiskIcon(change.risk_level)} {change.risk_level}</span>
          </div>

          <div class="meta">
            <span class="hash" title={change.commit_hash}>{formatHash(change.commit_hash)}</span>
            <span class="date">{formatDate(change.commit_date)}</span>
          </div>
        </div>

        <div class="message">
          {change.commit_message?.split('\n')[0] || 'No message'}
        </div>

        {#if change.tags?.length > 0}
          <div class="tags">
            {#each change.tags.slice(0, 5) as tag}
              <span class="tag">{tag}</span>
            {/each}
            {#if change.tags.length > 5}
              <span class="tag more">+{change.tags.length - 5}</span>
            {/if}
          </div>
        {/if}

        <div class="files">
          {#if change.files_changed?.length > 0}
            <span class="file-count">{change.files_changed.length} file(s)</span>
            <span class="file-name">{change.files_changed[0].split('/').pop()}</span>
            {#if change.files_changed.length > 1}
              <span class="more-files">+{change.files_changed.length - 1} more</span>
            {/if}
          {/if}
        </div>
      </div>
    {/each}
  </div>

  <div class="count">{changes.length} change(s) found</div>
{/if}

<style>
  .empty {
    text-align: center;
    padding: 4rem 2rem;
    color: #8b949e;
    font-style: italic;
  }

  .changes-list {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .change-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 1rem;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
  }

  .change-card:hover {
    border-color: #58a6ff;
    background: #1c2128;
  }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
  }

  .score-section {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .score {
    font-weight: bold;
    font-size: 1.1rem;
    padding: 0.2rem 0.5rem;
    border-radius: 4px;
    min-width: 1.5rem;
    text-align: center;
  }

  .score.high {
    background: #da3633;
    color: white;
  }

  .score.medium {
    background: #d29922;
    color: #0d1117;
  }

  .score.low {
    background: #2ea043;
    color: white;
  }

  .score.info {
    background: #8b949e;
    color: #0d1117;
  }

  .risk {
    font-size: 0.85rem;
    color: #8b949e;
    text-transform: capitalize;
  }

  .meta {
    display: flex;
    gap: 1rem;
    font-size: 0.85rem;
    color: #8b949e;
  }

  .hash {
    font-family: ui-monospace, monospace;
    background: #21262d;
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
  }

  .message {
    font-size: 0.95rem;
    margin-bottom: 0.75rem;
    color: #e6edf3;
    line-height: 1.4;
  }

  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-bottom: 0.75rem;
  }

  .tag {
    background: #388bfd33;
    color: #58a6ff;
    font-size: 0.75rem;
    padding: 0.15rem 0.5rem;
    border-radius: 12px;
  }

  .tag.more {
    background: #30363d;
    color: #8b949e;
  }

  .files {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8rem;
    color: #8b949e;
  }

  .file-count {
    background: #21262d;
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
  }

  .file-name {
    color: #a371f7;
  }

  .more-files {
    color: #484f58;
  }

  .count {
    text-align: center;
    margin-top: 1.5rem;
    color: #8b949e;
    font-size: 0.9rem;
  }
</style>
