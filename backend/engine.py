import asyncio
import json
import os
import time
from backend.security import Unavailable, Retryable, public_url
from backend.store import now
from backend.research import Source


class Engine:
    def __init__(self, store, tsenta, search, ollama):
        self.store = store
        self.tsenta = tsenta
        self.search = search
        self.ollama = ollama
        self.poll_enabled = os.getenv('TSENTA_POLL_ENABLED', 'false').lower() == 'true'
        self.poll_reference = os.getenv('TSENTA_POLL_SUPPORT_REFERENCE', '').strip()
        try:
            self.poll_seconds = float(os.getenv('TSENTA_POLL_SECONDS', '') or 0)
        except ValueError:
            self.poll_seconds = 0
        self.poll_active = self.poll_enabled and bool(self.poll_reference) and self.poll_seconds > 0
        self.stop = asyncio.Event()

    def scheduler_info(self):
        return {
            'enabled': self.poll_active,
            'interval_seconds': self.poll_seconds if self.poll_active else None,
            'support_reference': self.poll_reference,
            'message': 'Automatic checking enabled with the operator-provided interval.'
            if self.poll_active
            else 'Automatic checking is disabled. Use Sync now. A supported interval and reference are required before enabling recurring polling.',
        }

    def failure(self, table, key, identifier, error, attempt):
        blocked = isinstance(error, Unavailable)
        state = 'blocked' if blocked else ('failed' if attempt >= 3 else 'retry')
        delay = max(30 * (2 ** (attempt - 1)), getattr(error, 'retry_after', 0))
        message = (
            str(error)
            if isinstance(error, (Unavailable, Retryable))
            else 'Unexpected response or processing error. Data retained; inspect configuration and retry.'
        )
        with self.store.db() as db:
            db.execute(
                f'UPDATE {table} SET state=?,error=?,next_attempt=? WHERE {key}=?',
                (state, message, time.time() + delay, identifier),
            )
            if table == 'jobs':
                db.execute(
                    'UPDATE jobs SET stage=?,updated_at=? WHERE application_id=?',
                    (state, now(), identifier),
                )
                db.execute(
                    'UPDATE applications SET research_state=?,last_error=? WHERE source_application_id=?',
                    (state, message, identifier),
                )
            elif state in ('blocked', 'failed'):
                db.execute('UPDATE sync_runs SET finished_at=? WHERE id=?', (now(), identifier))

    async def tick(self):
        from backend.details import baseline_valid

        if not self.store.path.exists() or not baseline_valid(self.store):
            return
        if self.poll_active:
            last = self.store.rows('SELECT started_at FROM sync_runs ORDER BY id DESC LIMIT 1')
            from datetime import datetime

            last_time = datetime.fromisoformat(last[0]['started_at']).timestamp() if last else 0
            if time.time() - last_time >= self.poll_seconds:
                self.store.enqueue_sync()
        runs = self.store.rows(
            "SELECT * FROM sync_runs WHERE state IN ('queued','retry') AND next_attempt<=? ORDER BY id LIMIT 1",
            (time.time(),),
        )
        if runs:
            run = runs[0]
            attempt = run['attempts'] + 1
            if attempt > 3:
                self.failure(
                    'sync_runs',
                    'id',
                    run['id'],
                    Retryable('Sync retry limit reached. Use Sync now to try again.'),
                    attempt,
                )
                return
            with self.store.db() as db:
                db.execute(
                    "UPDATE sync_runs SET state='running',attempts=?,error=NULL WHERE id=?",
                    (attempt, run['id']),
                )
            try:
                rows = await self.tsenta.snapshot()
                result = self.store.apply_snapshot(rows)
                with self.store.db() as db:
                    db.execute(
                        "UPDATE sync_runs SET state='done',finished_at=?,observed=?,added=?,eligible=?,error=NULL WHERE id=?",
                        (now(), result['observed'], result['added'], result['eligible'], run['id']),
                    )
            except Exception as error:
                self.failure('sync_runs', 'id', run['id'], error, attempt)
            return
        jobs = self.store.rows(
            "SELECT * FROM jobs WHERE state IN ('queued','retry') AND next_attempt<=? ORDER BY rowid LIMIT 1",
            (time.time(),),
        )
        if not jobs:
            if (
                os.getenv('OUTREACH_AUTO_ROLE_EXTRACTION', 'true').lower() == 'true'
                and os.getenv('OUTREACH_DEMO', 'false').lower() != 'true'
            ):
                from backend.posting_role import fill_next_missing_role

                if await fill_next_missing_role(self.store):
                    return
            return
        job = jobs[0]
        aid = job['application_id']
        attempt = job['attempts'] + 1
        if attempt > 3:
            self.failure(
                'jobs',
                'application_id',
                aid,
                Retryable('Research retry limit reached. Retry from Applications.'),
                attempt,
            )
            return
        with self.store.db() as db:
            claimed = db.execute(
                "UPDATE jobs SET state='running',attempts=?,error=NULL WHERE application_id=? AND state IN ('queued','retry')",
                (attempt, aid),
            )
            if not claimed.rowcount:
                return
            db.execute(
                "UPDATE applications SET research_state='running',last_error=NULL WHERE source_application_id=?",
                (aid,),
            )
        try:
            await asyncio.wait_for(self.research(aid), timeout=600)
        except asyncio.TimeoutError:
            self.failure(
                'jobs',
                'application_id',
                aid,
                Unavailable(
                    'Preparation exceeded ten minutes. Retry to resume from saved sources.'
                ),
                attempt,
            )
        except Exception as error:
            self.failure('jobs', 'application_id', aid, error, attempt)

    async def research(self, aid):
        app = self.store.rows('SELECT * FROM applications WHERE source_application_id=?', (aid,))[0]
        if app['hiring_outcome'] in ('rejected', 'job_closed'):
            raise Unavailable(
                'Application is marked rejected or closed; new outreach preparation stopped.'
            )
        if app['source_status'] != 'COMPLETED' or (
            app['historical'] and app['confirmed_at_baseline'] and not app['selected']
        ):
            raise Unavailable('Application is not eligible for research.')
        from backend.posting_role import missing_details

        if missing_details(app['company'], app['role']):
            raise Unavailable('Add the company and role before preparing outreach.')
        if not hasattr(self, 'experience'):
            from backend.experience import ExperienceRepository

            self.experience = ExperienceRepository(self.store)
            self.experience.initialize()
        from backend.preparation import execute

        resume = bool(
            self.store.rows(
                'SELECT * FROM preparation_resume_requests WHERE application_id=?', (aid,)
            )
        )
        rid, complete, has_output = await execute(self, aid, resume=resume)
        with self.store.db() as db:
            db.execute('DELETE FROM preparation_resume_requests WHERE application_id=?', (aid,))
        if hasattr(self, 'resume_runs'):
            self.resume_runs.discard(aid)
        with self.store.db() as db:
            db.execute(
                'UPDATE jobs SET state=?,stage=?,updated_at=?,error=NULL WHERE application_id=?',
                (
                    'done' if complete else 'blocked',
                    'done' if complete else 'awaiting_review',
                    now(),
                    aid,
                ),
            )
            db.execute(
                'UPDATE applications SET research_state=?,last_error=? WHERE source_application_id=?',
                (
                    'ready'
                    if complete and has_output
                    else ('no_contacts' if complete else 'blocked'),
                    None if complete else 'Preparation paused. Review the run and resume.',
                    aid,
                ),
            )

    def recover_pending(self):
        # Graph checkpoints own progress; this restores only the scheduling projection.
        if not self.store.path.with_name(self.store.path.name + '.checkpoints.sqlite').exists():
            return
        with self.store.db() as db:
            db.execute("""UPDATE jobs SET state='queued',stage='queued',attempts=0,error=NULL WHERE state='interrupted'
                AND application_id IN (SELECT application_id FROM preparation_runs)
                AND application_id IN (SELECT source_application_id FROM applications WHERE source_status='COMPLETED'
                    AND hiring_outcome NOT IN ('rejected','job_closed'))""")

    async def run(self):
        while not self.stop.is_set():
            try:
                await self.tick()
            except Exception:
                # Keep a failed worker iteration from becoming an endless UI spinner.
                with self.store.db() as db:
                    db.execute(
                        "UPDATE jobs SET state='interrupted',stage='interrupted',updated_at=?,error='Worker interrupted. Retry preparation.' WHERE state='running'",
                        (now(),),
                    )
                    db.execute(
                        "UPDATE applications SET research_state='interrupted',last_error='Worker interrupted. Retry preparation.' WHERE source_application_id IN (SELECT application_id FROM jobs WHERE state='interrupted')"
                    )
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

    def stage(self, aid, stage):
        with self.store.db() as db:
            db.execute(
                'UPDATE jobs SET stage=?,updated_at=? WHERE application_id=?', (stage, now(), aid)
            )
