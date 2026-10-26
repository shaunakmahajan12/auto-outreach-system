import { useState } from 'react';
import { api } from './api';
export interface Configuration {
  approved_experience_count?: number;
  exact_note_200?: boolean;
  facts: { id: string; text: string }[];
  note_limit: number;
  dm_limit: number;
  tsenta_connected: boolean;
  search_configured: boolean;
  keychain_error: string | null;
  ollama: { available: boolean; model: string; message: string };
  scheduler: { enabled: boolean; message: string };
  demo: boolean;
  onboarding_required: boolean;
}
type Action = (key: string, fn: () => Promise<unknown>, success?: string) => Promise<void>;
export function SettingsView({
  config: c,
  action,
  refreshSettings,
  openExperience,
}: {
  config: Configuration;
  action: Action;
  refreshSettings: () => Promise<void>;
  openExperience: () => void;
}) {
  const [exact, setExact] = useState(c.exact_note_200 !== false),
    [noteLimit, setNoteLimit] = useState(
      c.exact_note_200 !== false ? 200 : Math.min(c.note_limit, 200),
    ),
    [dmLimit, setDmLimit] = useState(c.dm_limit),
    [key, setKey] = useState(''),
    [authUrl, setAuthUrl] = useState(''),
    [feedback, setFeedback] = useState<{
      status: string;
      observations: number;
      acceptance_rate: number | null;
      edit_rate: number | null;
    } | null>(null);
  const setupComplete =
    !c.onboarding_required &&
    c.tsenta_connected &&
    c.search_configured &&
    c.ollama.available &&
    (c.approved_experience_count || 0) > 0;
  return (
    <div className="settings-grid">
      {!c.demo && !setupComplete && (
        <section className="panel settings-card settings-sources" aria-label="Workspace setup">
          <h2>Set up your workspace</h2>
          <p className="hint">
            Complete these steps to prepare outreach. Imported history stays available for review;
            choose historical applications explicitly before researching them.
          </p>
          <ol>
            <li>{c.tsenta_connected ? 'Connected' : 'Connect Tsenta using Sources below.'}</li>
            <li>
              {c.onboarding_required
                ? 'Import your complete initial history using Sources below.'
                : 'Initial history imported.'}
            </li>
            <li>
              {c.search_configured
                ? 'Contact research configured.'
                : 'Save your Serper key using Sources below.'}
            </li>
            <li>
              {c.ollama.available
                ? 'Local model ready.'
                : 'Start Ollama and install the model shown below, then Check health.'}
            </li>
            <li>
              {(c.approved_experience_count || 0) > 0
                ? `${c.approved_experience_count} approved experience records ready.`
                : 'Add experience and approve the facts you want to use.'}
            </li>
          </ol>
          <div className="button-row">
            <button className="button" disabled={c.onboarding_required} onClick={openExperience}>
              Add approved experience
            </button>
            <button className="button" onClick={() => action('setup-health', refreshSettings)}>
              Refresh setup status
            </button>
          </div>
        </section>
      )}
      <section className="panel settings-card settings-sources">
        <h2>Sources</h2>
        <div className="setting-row">
          <div>
            <h3>Tsenta applications</h3>
            <p className="hint">
              {c.tsenta_connected ? 'Connected · read-only application history' : 'Not connected'}
            </p>
          </div>
          <button
            className="button"
            disabled={c.demo}
            onClick={() =>
              action('connect', async () => {
                const result = await api<{ url: string }>('/tsenta/connect', 'POST');
                setAuthUrl(result.url);
              })
            }
          >
            {c.tsenta_connected ? 'Reconnect' : 'Configure Tsenta'}
          </button>
        </div>
        {c.keychain_error && (
          <p role="alert" className="danger">
            {c.keychain_error}
          </p>
        )}
        {authUrl && <a href={authUrl}>Continue to Tsenta sign-in ↗</a>}
        {c.onboarding_required && (
          <button
            className="button primary"
            disabled={!c.tsenta_connected}
            onClick={() =>
              action(
                'initialize',
                async () => {
                  await api('/onboarding/initialize', 'POST');
                  await refreshSettings();
                },
                'Initial history imported.',
              )
            }
          >
            Import initial history
          </button>
        )}
        <div className="setting-row">
          <div>
            <h3>Contact research</h3>
            <p className="hint">Serper · {c.search_configured ? 'Configured' : 'Unavailable'}</p>
          </div>
        </div>
        <label className="field">
          Serper API key
          <input
            type="password"
            autoComplete="off"
            value={key}
            onChange={e => setKey(e.target.value)}
            disabled={c.demo}
            placeholder="Enter a new key"
          />
        </label>
        <button
          className="button"
          disabled={!key || c.demo}
          onClick={() =>
            action(
              'key',
              async () => {
                await api('/settings/search-key', 'POST', { key });
                setKey('');
                await refreshSettings();
              },
              'Search key saved securely.',
            )
          }
        >
          Save key
        </button>
        <details className="secondary-details">
          <summary>Advanced source configuration</summary>
          <p className="hint">{c.scheduler.message}</p>
          <div className="button-row">
            {c.tsenta_connected && (
              <button
                className="button small"
                onClick={() =>
                  action('disconnect', async () => {
                    await api('/tsenta/connection', 'DELETE');
                    await refreshSettings();
                  })
                }
              >
                Disconnect Tsenta locally
              </button>
            )}
            {c.search_configured && (
              <button
                className="button small"
                onClick={() =>
                  action('remove-key', async () => {
                    await api('/settings/search-key', 'DELETE');
                    await refreshSettings();
                  })
                }
              >
                Remove search key
              </button>
            )}
          </div>
        </details>
      </section>
      <section className="panel settings-card">
        <h2>Model & Retrieval</h2>
        <div className="setting-row">
          <div>
            <h3>{c.ollama.model}</h3>
            <p className="hint">{c.ollama.message}</p>
          </div>
          <span className={'status-badge ' + (c.ollama.available ? 'green' : 'amber')}>
            {c.ollama.available ? 'Ready' : 'Unavailable'}
          </span>
        </div>
        <button className="button" onClick={() => action('health', refreshSettings)}>
          Check health
        </button>
        <p className="hint">
          Approved experience is retrieved for the job requirements. Similarity alone does not
          establish a qualification.
        </p>
        <details className="secondary-details">
          <summary>Advanced configuration</summary>
          <p className="hint">
            Configure OLLAMA_URL, EMBEDDING_MODEL, EMBEDDING_VERSION and
            RETRIEVAL_EMBEDDING_THRESHOLD in the environment. Restart after changes.
          </p>
          <code>
            ollama serve
            <br />
            ollama pull {c.ollama.model}
          </code>
        </details>
      </section>
      <section className="panel settings-card">
        <h2>Draft Preferences</h2>
        <label className="check-field">
          <input
            type="checkbox"
            checked={exact}
            onChange={e => {
              setExact(e.target.checked);
              if (e.target.checked) setNoteLimit(200);
            }}
          />
          Generated connection notes contain exactly 200 characters
        </label>
        <p className="hint">
          Manual edits must also fit the connection-note limit before they can be saved or copied.
        </p>
        <div className="limits">
          <label className="field">
            Connection-note character limit
            <input
              type="number"
              min={80}
              max={200}
              disabled={exact}
              value={noteLimit}
              onChange={e => setNoteLimit(Number(e.target.value))}
            />
          </label>
          <label className="field">
            DM limit
            <input
              type="number"
              min={300}
              max={5000}
              value={dmLimit}
              onChange={e => setDmLimit(Number(e.target.value))}
            />
          </label>
        </div>
        <button
          className="button primary"
          disabled={c.onboarding_required}
          onClick={() =>
            action(
              'preferences',
              async () => {
                await api('/settings', 'POST', {
                  facts_text: c.facts.map(f => f.text).join('\n'),
                  facts_approved: true,
                  note_limit: noteLimit,
                  dm_limit: dmLimit,
                  exact_note_200: exact,
                });
                await refreshSettings();
              },
              'Draft preferences saved.',
            )
          }
        >
          Save draft settings
        </button>
      </section>
      <section className="panel settings-card">
        <h2>Maintenance</h2>
        <p className="hint">
          Repair recognizable generated notes. Edited drafts and recorded activity are preserved; a
          private backup is created first.
        </p>
        <button
          className="button"
          disabled={c.onboarding_required}
          onClick={() =>
            action(
              'repair-notes',
              () => api('/maintenance/repair-notes', 'POST'),
              'Note repair completed. Review the results in the queue.',
            )
          }
        >
          Repair generated notes
        </button>
        <details className="secondary-details">
          <summary>Backup & restore</summary>
          <p className="hint">
            Stop the app and back up the configured SQLite database and its checkpoint sidecar
            together. Restore both before restarting. PostgreSQL deployments should use a database
            snapshot.
          </p>
          <p className="hint">
            See docs/operations.md for exact backup, restore and migration commands.
          </p>
        </details>
        <details className="secondary-details">
          <summary>Suggestion feedback</summary>
          <button
            className="button small"
            onClick={() =>
              action('feedback', async () => setFeedback(await api('/metrics/feedback')))
            }
          >
            Refresh feedback
          </button>
          <p className="hint">
            {!feedback || feedback.status === 'insufficient data'
              ? 'Not enough data'
              : `${feedback.observations} message observations · accepted ${Math.round((feedback.acceptance_rate || 0) * 100)}% · edited ${feedback.edit_rate == null ? 'Not enough data' : Math.round(feedback.edit_rate * 100) + '%'}`}
          </p>
        </details>
      </section>
    </div>
  );
}
