import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { Dialog } from './DraftDialog';
export interface Experience {
  id: string;
  text: string;
  project: string;
  technologies: string[];
  source_reference: string;
  status: 'draft' | 'approved' | 'retired';
  version: number;
  updated_at: string;
}
interface Description {
  text: string;
  source_url: string;
  provenance: string;
  updated_at: string;
  version: number;
}
interface Evidence {
  fact_id: string;
  text: string;
  reason: string;
  source_reference: string;
}
interface Requirement {
  text: string;
  category: string;
  priority: string;
  excerpt: string;
  assessment: 'supported' | 'uncertain' | 'unsupported';
  unsupported: boolean;
  supporting_facts: Evidence[];
  possible_evidence?: Evidence[];
}
export interface Matching {
  method: string;
  description_provenance?: Description;
  warning?: string;
  unsupported_meaning: string;
  matches: Requirement[];
  requirements: Requirement[];
}
interface Run {
  run_id: string;
  complete: boolean;
  next: string[];
  interrupts: { reason: string; action: string }[];
}
export function DescriptionReview({
  application,
  onSaved,
}: {
  application: { source_application_id: string };
  onSaved: () => Promise<void>;
}) {
  const aid = encodeURIComponent(application.source_application_id),
    epoch = useRef(0);
  const [description, setDescription] = useState(''),
    [url, setUrl] = useState(''),
    [provenance, setProvenance] = useState<Description | null>(null),
    [matching, setMatching] = useState<Matching | null>(null),
    [run, setRun] = useState<Run | null>(null),
    [loaded, setLoaded] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [reload, setReload] = useState(0),
    [message, setMessage] = useState('');
  useEffect(() => {
    const request = ++epoch.current;
    setLoaded(false);
    setDescription('');
    setUrl('');
    setProvenance(null);
    setMatching(null);
    setRun(null);
    setError('');
    setMessage('');
    setBusy(false);
    api<Description>(`/applications/${aid}/description`)
      .then(r => {
        if (request === epoch.current) {
          setDescription(r.text);
          setUrl(r.source_url);
          setProvenance(r);
          setLoaded(true);
        }
      })
      .catch((e: Error) => {
        if (request === epoch.current) setError(e.message);
      });
    return () => {
      epoch.current++;
    };
  }, [aid, reload]);
  async function perform(fn: () => Promise<void>) {
    const request = epoch.current;
    setBusy(true);
    setError('');
    try {
      await fn();
    } catch (e) {
      if (request === epoch.current) setError((e as Error).message);
    } finally {
      if (request === epoch.current) setBusy(false);
    }
  }
  return (
    <section className="panel settings-card description-review">
      <div className="section-heading">
        <div>
          <h3>Job description</h3>
          <p className="hint">Use the description for this specific application.</p>
        </div>
        {provenance && (
          <span className="hint">
            v{provenance.version} · {new Date(provenance.updated_at).toLocaleDateString()}
          </span>
        )}
      </div>
      {!loaded && !error && <p role="status">Loading description…</p>}
      <label className="field">
        Job description
        <textarea
          aria-label="Job description"
          disabled={!loaded || busy}
          rows={5}
          maxLength={5000}
          value={description}
          onChange={e => setDescription(e.target.value)}
        />
      </label>
      <label className="field">
        Description source URL
        <input
          aria-label="Description source URL"
          disabled={!loaded || busy}
          value={url}
          onChange={e => setUrl(e.target.value)}
          placeholder="https://…"
        />
      </label>
      <div className="button-row">
        <button
          className="button primary"
          disabled={!loaded || busy}
          onClick={() =>
            perform(async () => {
              const request = epoch.current;
              await api(`/applications/${aid}/description`, 'PUT', {
                text: description,
                source_url: url,
              });
              const next = await api<Description>(`/applications/${aid}/description`);
              if (request !== epoch.current) return;
              setMatching(null);
              setProvenance(next);
              setMessage('Description saved.');
              await onSaved();
            })
          }
        >
          Save description
        </button>
        <button
          className="button"
          disabled={!loaded || busy}
          onClick={() =>
            perform(async () => {
              const request = epoch.current;
              const next = await api<Matching>(`/applications/${aid}/matches`, 'POST');
              if (request === epoch.current) setMatching(next);
            })
          }
        >
          Review requirement matches
        </button>
        <button
          className="text-button"
          disabled={!loaded || busy}
          onClick={() =>
            perform(async () => {
              const request = epoch.current;
              const next = await api<Run>(`/applications/${aid}/preparation`);
              if (request === epoch.current) setRun(next);
            })
          }
        >
          Check preparation run
        </button>
      </div>
      {message && (
        <p role="status" className="hint">
          {message}
        </p>
      )}
      {error && (
        <p role="alert" className="danger">
          {error}
          {!loaded && (
            <button className="button small" onClick={() => setReload(reload + 1)}>
              Retry loading
            </button>
          )}
        </p>
      )}
      {matching && <MatchPanel matching={matching} />}
      {run && (
        <details open className="secondary-details">
          <summary>
            Preparation · {run.complete ? 'Saved' : run.next.join(', ') || 'Not started'}
          </summary>
          <small>Run {run.run_id}</small>
          {run.interrupts.map((i, n) => (
            <p key={n}>
              {i.reason}: {i.action}
            </p>
          ))}
          {!run.complete && !run.next.length && (
            <button
              className="button"
              onClick={() =>
                perform(async () => {
                  await api(`/applications/${aid}/research`, 'POST');
                  await onSaved();
                  setRun(null);
                })
              }
            >
              Prepare current version
            </button>
          )}
          {!!run.interrupts.length && (
            <button
              className="button"
              onClick={() =>
                perform(async () => {
                  await api(`/applications/${aid}/preparation/resume`, 'POST');
                  await onSaved();
                  setRun(null);
                })
              }
            >
              Resume preparation
            </button>
          )}
        </details>
      )}
    </section>
  );
}
export function MatchPanel({ matching: m }: { matching: Matching }) {
  return (
    <div className="match-review">
      <h4>{m.method}</h4>
      {m.description_provenance && (
        <p className="hint">
          {m.description_provenance.provenance} · version {m.description_provenance.version}
          {m.description_provenance.source_url && (
            <>
              {' '}
              ·{' '}
              <a href={m.description_provenance.source_url} target="_blank" rel="noreferrer">
                Source ↗
              </a>
            </>
          )}
        </p>
      )}
      {m.warning && <p role="status">{m.warning}</p>}
      <p className="hint">{m.unsupported_meaning}</p>
      {m.matches?.map((r, i) => (
        <article key={i}>
          <strong>{r.text}</strong>
          <p>
            <span className={'status-badge ' + (r.assessment === 'supported' ? 'green' : 'amber')}>
              {r.assessment === 'supported'
                ? 'Supported'
                : r.assessment === 'uncertain'
                  ? 'Uncertain — review evidence'
                  : 'Unsupported by approved evidence'}
            </span>{' '}
            · {r.category} · {r.priority}
          </p>
          <details>
            <summary>Evidence & excerpt</summary>
            <blockquote>{r.excerpt}</blockquote>
            {[...r.supporting_facts, ...(r.possible_evidence || [])].map(f => (
              <p key={f.fact_id}>
                {f.text}
                <br />
                <small>
                  {f.reason} · Source: {f.source_reference || 'not supplied'} · {f.fact_id}
                </small>
              </p>
            ))}
          </details>
        </article>
      ))}
      {!m.requirements?.length && (
        <p>Role-based fallback: add a description for requirement matching.</p>
      )}
    </div>
  );
}
const blank = {
  text: '',
  project: '',
  technologies: [] as string[],
  source_reference: '',
  status: 'draft' as Experience['status'],
};
export function ExperienceManager() {
  const [rows, setRows] = useState<Experience[]>([]),
    [value, setValue] = useState(blank),
    [technologies, setTechnologies] = useState(''),
    [id, setId] = useState<string | null>(null),
    [error, setError] = useState(''),
    [query, setQuery] = useState(''),
    [open, setOpen] = useState(false),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false);
  async function refresh() {
    setRows((await api<{ experience: Experience[] }>('/experience')).experience);
    setLoading(false);
  }
  useEffect(() => {
    refresh().catch((e: Error) => {
      setError(e.message);
      setLoading(false);
    });
  }, []);
  async function save() {
    setBusy(true);
    try {
      setError('');
      await api(
        id ? `/experience/${encodeURIComponent(id)}` : '/experience',
        id ? 'PUT' : 'POST',
        value,
      );
      setOpen(false);
      setValue(blank);
      setId(null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function status(r: Experience, status: Experience['status']) {
    setBusy(true);
    try {
      await api(`/experience/${encodeURIComponent(r.id)}`, 'PUT', {
        text: r.text,
        project: r.project,
        technologies: r.technologies,
        source_reference: r.source_reference,
        status,
      });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const filtered = rows.filter(r =>
    [r.text, r.project, r.technologies.join(' '), r.source_reference]
      .join(' ')
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <section className="experience-page">
      <div className="panel toolbar">
        <label className="search-field">
          Search experience
          <input
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Project, technology or fact"
          />
        </label>
        <span className="hint">
          {filtered.length} {filtered.length === 1 ? 'record' : 'records'}
        </span>
        <button
          className="button primary"
          onClick={() => {
            setValue(blank);
            setTechnologies('');
            setId(null);
            setError('');
            setOpen(true);
          }}
        >
          Add experience
        </button>
      </div>
      <p className="hint">
        Only approved facts are used in drafts. Editing approved content requires renewed approval.
      </p>
      {error && !open && (
        <p role="alert" className="notice error">
          {error}
        </p>
      )}
      {loading && <p role="status">Loading experience…</p>}
      <div className="experience-list">
        {filtered.map(r => (
          <article className="panel experience-record" key={r.id}>
            <div>
              <div className="section-heading">
                <h3>{r.project || 'Independent experience'}</h3>
                <span className={'status-badge ' + (r.status === 'approved' ? 'green' : 'neutral')}>
                  {r.status}
                </span>
              </div>
              <p>{r.text}</p>
              <div className="badge-row">
                {r.technologies.map(t => (
                  <span className="technology-chip" key={t}>
                    {t}
                  </span>
                ))}
              </div>
              <p className="hint">Source: {r.source_reference || 'Not supplied'}</p>
              <details>
                <summary>Record details</summary>
                <small>
                  {r.id} · version {r.version} · {new Date(r.updated_at).toLocaleString()}
                </small>
              </details>
            </div>
            <div className="button-row">
              <button
                className="button small"
                onClick={() => {
                  setId(r.id);
                  setValue({
                    text: r.text,
                    project: r.project,
                    technologies: r.technologies,
                    source_reference: r.source_reference,
                    status: r.status,
                  });
                  setTechnologies(r.technologies.join(', '));
                  setError('');
                  setOpen(true);
                }}
              >
                Edit experience
              </button>
              {r.status !== 'approved' && (
                <button
                  className="button small"
                  disabled={busy}
                  onClick={() => status(r, 'approved')}
                >
                  Approve
                </button>
              )}
              {r.status !== 'retired' && (
                <button
                  className="text-button"
                  disabled={busy}
                  onClick={() => status(r, 'retired')}
                >
                  Retire
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
      {!loading && !filtered.length && (
        <div className="panel empty">
          <h2>{rows.length ? 'No matching experience' : 'Add your first experience'}</h2>
          <p>Save factual project or employer evidence, then approve it for drafting.</p>
          <button
            className="button primary"
            onClick={() => {
              setValue(blank);
              setTechnologies('');
              setId(null);
              setOpen(true);
            }}
          >
            Add experience
          </button>
        </div>
      )}
      {open && (
        <Dialog
          title={id ? 'Edit experience' : 'Add experience'}
          onClose={() => {
            if (!busy) setOpen(false);
          }}
        >
          <div className="dialog-body form-stack">
            {error && (
              <p role="alert" className="notice error">
                {error}
              </p>
            )}
            <label className="field">
              Factual text
              <textarea
                aria-label="Factual text"
                value={value.text}
                onChange={e => setValue({ ...value, text: e.target.value, status: 'draft' })}
              />
            </label>
            {value.text.length > 300 && (
              <p className="hint" role="status">
                Long facts rarely fit a connection note and may be left out of DMs, because drafts
                use whole facts only. Consider splitting this into concise facts.
              </p>
            )}
            <label className="field">
              Project or employer
              <input
                value={value.project}
                onChange={e => setValue({ ...value, project: e.target.value, status: 'draft' })}
              />
            </label>
            <label className="field">
              Technologies (comma separated)
              <input
                value={technologies}
                onChange={e => {
                  setTechnologies(e.target.value);
                  setValue({
                    ...value,
                    technologies: e.target.value
                      .split(',')
                      .map(s => s.trim())
                      .filter(Boolean),
                    status: 'draft',
                  });
                }}
              />
            </label>
            <label className="field">
              Source reference
              <input
                value={value.source_reference}
                onChange={e =>
                  setValue({ ...value, source_reference: e.target.value, status: 'draft' })
                }
              />
            </label>
            <label className="field">
              Approval status
              <select
                aria-label="Approval status"
                value={value.status}
                onChange={e =>
                  setValue({ ...value, status: e.target.value as Experience['status'] })
                }
              >
                <option value="draft">Draft</option>
                <option value="approved">Approved — I verified this fact</option>
                <option value="retired">Retired</option>
              </select>
            </label>
            <p className="hint">After changing content, explicitly approve the updated fact.</p>
            <button className="button primary" disabled={busy || !value.text.trim()} onClick={save}>
              {busy ? 'Saving…' : 'Save experience'}
            </button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
